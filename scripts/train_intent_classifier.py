"""
Fine-tuning script for XLM-RoBERTa-base on the 7-class Khmer-English intent dataset.
Track B: Generates lightweight model weights (< 500 MB) for CPU sub-50ms inference.
"""

import json
import os
import argparse
import torch
from torch.utils.data import Dataset, DataLoader
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    get_linear_schedule_with_warmup,
)
from invoicemate.services.khmer_normalizer import segment_khmer_text

INTENT_LABELS = [
    "create_draft",
    "update_draft",
    "confirm",
    "cancel",
    "search",
    "select_customer",
    "clarify_needed",
]
LABEL2ID = {lbl: idx for idx, lbl in enumerate(INTENT_LABELS)}
ID2LABEL = {idx: lbl for idx, lbl in enumerate(INTENT_LABELS)}


class IntentDataset(Dataset):
    def __init__(self, texts, labels, tokenizer, max_length=128):
        self.texts = [segment_khmer_text(t) for t in texts]
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, idx):
        text = self.texts[idx]
        label = self.labels[idx]
        encoding = self.tokenizer(
            text,
            truncation=True,
            max_length=self.max_length,
            padding="max_length",
            return_tensors="pt",
        )
        return {
            "input_ids": encoding["input_ids"].squeeze(0),
            "attention_mask": encoding["attention_mask"].squeeze(0),
            "labels": torch.tensor(label, dtype=torch.long),
        }


def load_dataset(dataset_path: str):
    texts, labels = [], []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            intent = item.get("intent")
            if intent in LABEL2ID:
                texts.append(item.get("text", ""))
                labels.append(LABEL2ID[intent])
    return texts, labels


def train(
    dataset_path: str = "data/intent_dataset.jsonl",
    output_dir: str = "models/intent_classifier",
    model_name: str = "xlm-roberta-base",
    epochs: int = 5,
    batch_size: int = 8,
    lr: float = 2e-5,
):
    print(f"Loading dataset from {dataset_path}...")
    texts, labels = load_dataset(dataset_path)
    print(f"Loaded {len(texts)} samples across {len(INTENT_LABELS)} intent classes.")

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=len(INTENT_LABELS),
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    dataset = IntentDataset(texts, labels, tokenizer)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    total_steps = len(dataloader) * epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=int(total_steps * 0.1), num_training_steps=total_steps)

    model.train()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    print(f"Starting training on device: {device}...")
    for epoch in range(1, epochs + 1):
        total_loss = 0
        correct = 0
        total = 0
        for batch in dataloader:
            optimizer.zero_grad()
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            target_labels = batch["labels"].to(device)

            outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=target_labels)
            loss = outputs.loss
            loss.backward()
            optimizer.step()
            scheduler.step()

            total_loss += loss.item()
            preds = torch.argmax(outputs.logits, dim=-1)
            correct += (preds == target_labels).sum().item()
            total += target_labels.size(0)

        acc = (correct / total) * 100
        print(f"Epoch {epoch}/{epochs} | Loss: {total_loss / len(dataloader):.4f} | Accuracy: {acc:.2f}%")

    os.makedirs(output_dir, exist_ok=True)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"Model successfully saved to {output_dir}!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train XLM-RoBERTa Intent Classifier")
    parser.add_argument("--dataset", default="data/intent_dataset.jsonl", help="Path to jsonl dataset")
    parser.add_argument("--output", default="models/intent_classifier", help="Path to output model dir")
    parser.add_argument("--model", default="xlm-roberta-base", help="Base model name")
    parser.add_argument("--epochs", type=int, default=5, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=8, help="Batch size")
    args = parser.parse_args()

    train(
        dataset_path=args.dataset,
        output_dir=args.output,
        model_name=args.model,
        epochs=args.epochs,
        batch_size=args.batch_size,
    )

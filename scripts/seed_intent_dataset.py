"""
Generate and curate a balanced 175-example Khmer-English commercial dataset
for fine-tuning XLM-RoBERTa-base (Track B).
"""

import json
import os
import datetime

OUTPUT_PATH = "data/intent_dataset.jsonl"

DATASET_SAMPLES = [
    # =========================================================================
    # 1. CREATE_DRAFT (60 examples: English, Khmer, Mixed)
    # =========================================================================
    # English (20)
    {"text": "Invoice Sokha 2 monitors at $450 each", "intent": "create_draft", "customer": "Sokha", "lang": "en"},
    {"text": "Bill Dara 10 consulting hours at $75 per hour", "intent": "create_draft", "customer": "Dara", "lang": "en"},
    {"text": "Create invoice for Bopha Coffee 5 bags of coffee beans at $12", "intent": "create_draft", "customer": "Bopha Coffee", "lang": "en"},
    {"text": "Invoice Vandy 1 logistics service at $150", "intent": "create_draft", "customer": "Vandy", "lang": "en"},
    {"text": "Bill Rithy 3 desk lamps at $35 each", "intent": "create_draft", "customer": "Rithy", "lang": "en"},
    {"text": "Invoice Chan 100000 KHR for delivery", "intent": "create_draft", "customer": "Chan", "lang": "en"},
    {"text": "Bill Sophal 4 chairs at $50 each due in 14 days", "intent": "create_draft", "customer": "Sophal", "lang": "en"},
    {"text": "Invoice Piseth $500 for web development", "intent": "create_draft", "customer": "Piseth", "lang": "en"},
    {"text": "Invoice Nary 12 notebooks at $2.50 each", "intent": "create_draft", "customer": "Nary", "lang": "en"},
    {"text": "Bill Maly 1 printing job at $80", "intent": "create_draft", "customer": "Maly", "lang": "en"},
    {"text": "Send invoice to Mengly 2 keyboards at $30 each", "intent": "create_draft", "customer": "Mengly", "lang": "en"},
    {"text": "Bill Kiri 5 t-shirts at $8 each", "intent": "create_draft", "customer": "Kiri", "lang": "en"},
    {"text": "Invoice Lina 1 social media marketing package at $300", "intent": "create_draft", "customer": "Lina", "lang": "en"},
    {"text": "Charge Socheat $120 for air conditioner repair", "intent": "create_draft", "customer": "Socheat", "lang": "en"},
    {"text": "Create invoice for Angkor Mart 20 cartons of water at $4", "intent": "create_draft", "customer": "Angkor Mart", "lang": "en"},
    {"text": "Bill Sovann 3 headsets at $25 each", "intent": "create_draft", "customer": "Sovann", "lang": "en"},
    {"text": "Invoice Chenda 1 translation service at $60", "intent": "create_draft", "customer": "Chenda", "lang": "en"},
    {"text": "Bill Bunthorn 8 security cameras at $90 each", "intent": "create_draft", "customer": "Bunthorn", "lang": "en"},
    {"text": "Invoice Sreymom 2 office desks at $110 each", "intent": "create_draft", "customer": "Sreymom", "lang": "en"},
    {"text": "Bill Panha $400 for mobile app design", "intent": "create_draft", "customer": "Panha", "lang": "en"},

    # Khmer (20)
    {"text": "គិតលុយ តារា ម៉ូនីទ័រ ២ គ្រឿង តម្លៃ ៤៥០ ដុល្លារ", "intent": "create_draft", "customer": "តារា", "lang": "km"},
    {"text": "ធ្វើវិក្កយបត្រឱ្យ សុខា កាហ្វេ ៥ ថង់ តម្លៃ ១២$", "intent": "create_draft", "customer": "សុខា", "lang": "km"},
    {"text": "ចេញវិក្កយបត្រជូន បុប្ផា សេវាដឹកជញ្ជូន ៤០០០០ រៀល", "intent": "create_draft", "customer": "បុប្ផា", "lang": "km"},
    {"text": "គិតលុយ វ៉ាន់ឌី កៅអី ៤ តម្លៃ ៥០ ដុល្លារក្នុងមួយគ្រឿង", "intent": "create_draft", "customer": "វ៉ាន់ឌី", "lang": "km"},
    {"text": "ធ្វើវិក្កយបត្រជូន រិទ្ធី តុធ្វើការ ១ តម្លៃ ៨០$", "intent": "create_draft", "customer": "រិទ្ធី", "lang": "km"},
    {"text": "គិតលុយ ចាន់ សេវាជួសជុលកុំព្យូទ័រ ៣០ ដុល្លារ", "intent": "create_draft", "customer": "ចាន់", "lang": "km"},
    {"text": "ចេញវិក្កយបត្រឱ្យ ពិសិដ្ឋ រចនាគេហទំព័រ ៥០០$", "intent": "create_draft", "customer": "ពិសិដ្ឋ", "lang": "km"},
    {"text": "ធ្វើវិក្កយបត្រជូន ណារី សៀវភៅ ១២ ក្បាល ថ្លៃ ២.៥០$", "intent": "create_draft", "customer": "ណារី", "lang": "km"},
    {"text": "គិតលុយ ម៉ាលី បោះពុម្ពធៀបការ ១០០ សន្លឹក ថ្លៃ ៤០ ដុល្លារ", "intent": "create_draft", "customer": "ម៉ាលី", "lang": "km"},
    {"text": "ធ្វើវិក្កយបត្រឱ្យ គីរី អាវយឺត ៥ ថ្លៃ ៨$", "intent": "create_draft", "customer": "គីរី", "lang": "km"},
    {"text": "គិតលុយ សុផល ជើងទម្រទូរស័ព្ទ ២ ថ្លៃ ១៥$", "intent": "create_draft", "customer": "សុផល", "lang": "km"},
    {"text": "ចេញវិក្កយបត្រជូន លីណា សេវាទីផ្សារ ៣០០ ដុល្លារ", "intent": "create_draft", "customer": "លីណា", "lang": "km"},
    {"text": "គិតលុយ សុជាតិ ជួសជុលម៉ាស៊ីនត្រជាក់ ៤៨០០០០ រៀល", "intent": "create_draft", "customer": "សុជាតិ", "lang": "km"},
    {"text": "ធ្វើវិក្កយបត្រជូន សុវណ្ណ កាសត្រចៀក ៣ ថ្លៃ ២៥$", "intent": "create_draft", "customer": "សុវណ្ណ", "lang": "km"},
    {"text": "គិតលុយ ចិន្តា បកប្រែឯកសារ ៦០ ដុល្លារ", "intent": "create_draft", "customer": "ចិន្តា", "lang": "km"},
    {"text": "ចេញវិក្កយបត្រឱ្យ ប៊ុនថន កាមេរ៉ាសុវត្ថិភាព ៤ ថ្លៃ ៩០$", "intent": "create_draft", "customer": "ប៊ុនថន", "lang": "km"},
    {"text": "គិតលុយ ស្រីមុំ កុំព្យូទ័រយួរដៃ ១ ថ្លៃ ៦៥០ ដុល្លារ", "intent": "create_draft", "customer": "ស្រីមុំ", "lang": "km"},
    {"text": "ធ្វើវិក្កយបត្រជូន បញ្ញា ទឹកក្រូច ១០ កេស ថ្លៃ ៨០$", "intent": "create_draft", "customer": "បញ្ញា", "lang": "km"},
    {"text": "គិតលុយ មេងលី សេវាសម្អាតការិយាល័យ ៧០ ដុល្លារ", "intent": "create_draft", "customer": "មេងលី", "lang": "km"},
    {"text": "ចេញវិក្កយបត្រជូន ធារ៉ា ថ្លៃដឹកទំនិញ ២០០០០ រៀល", "intent": "create_draft", "customer": "ធារ៉ា", "lang": "km"},

    # Mixed Code-switched (20)
    {"text": "ធ្វើ invoice ឲ្យ Dara $50 សម្រាប់ website design", "intent": "create_draft", "customer": "Dara", "lang": "mixed"},
    {"text": "គិតលុយ Sokha 2 monitors at $450", "intent": "create_draft", "customer": "Sokha", "lang": "mixed"},
    {"text": "Invoice Bopha Coffee 5 bags at $12 per bag", "intent": "create_draft", "customer": "Bopha Coffee", "lang": "mixed"},
    {"text": "ធ្វើ invoice ជូន Vandy 1 logistics service ថ្លៃ $150", "intent": "create_draft", "customer": "Vandy", "lang": "mixed"},
    {"text": "Bill Rithy 3 lamps ថ្លៃ $35 each", "intent": "create_draft", "customer": "Rithy", "lang": "mixed"},
    {"text": "គិតលុយ Chan 100000 KHR សម្រាប់ delivery", "intent": "create_draft", "customer": "Chan", "lang": "mixed"},
    {"text": "ធ្វើ invoice ឱ្យ Sophal 4 chairs at $50 each", "intent": "create_draft", "customer": "Sophal", "lang": "mixed"},
    {"text": "Invoice Piseth $500 សម្រាប់ web development", "intent": "create_draft", "customer": "Piseth", "lang": "mixed"},
    {"text": "Bill Nary 12 notebooks ថ្លៃ $2.50", "intent": "create_draft", "customer": "Nary", "lang": "mixed"},
    {"text": "គិតលុយ Maly 1 printing job at $80", "intent": "create_draft", "customer": "Maly", "lang": "mixed"},
    {"text": "ធ្វើ invoice ឲ្យ Mengly 2 keyboards at $30 each", "intent": "create_draft", "customer": "Mengly", "lang": "mixed"},
    {"text": "Bill Kiri 5 shirts ថ្លៃ $8 ក្នុងមួយអាវ", "intent": "create_draft", "customer": "Kiri", "lang": "mixed"},
    {"text": "Invoice Lina $300 សម្រាប់ marketing service", "intent": "create_draft", "customer": "Lina", "lang": "mixed"},
    {"text": "គិតលុយ Socheat $120 សម្រាប់ aircon service", "intent": "create_draft", "customer": "Socheat", "lang": "mixed"},
    {"text": "ធ្វើ invoice ឱ្យ Angkor Mart 20 packs of water at $4", "intent": "create_draft", "customer": "Angkor Mart", "lang": "mixed"},
    {"text": "Bill Sovann 3 headsets ថ្លៃ $25 ក្នុងមួយគ្រឿង", "intent": "create_draft", "customer": "Sovann", "lang": "mixed"},
    {"text": "Invoice Chenda $60 សម្រាប់ translation", "intent": "create_draft", "customer": "Chenda", "lang": "mixed"},
    {"text": "គិតលុយ Bunthorn 8 cameras at $90 each", "intent": "create_draft", "customer": "Bunthorn", "lang": "mixed"},
    {"text": "ធ្វើ invoice ឲ្យ Sreymom 2 desks at $110", "intent": "create_draft", "customer": "Sreymom", "lang": "mixed"},
    {"text": "Bill Panha $400 សម្រាប់ UI UX design", "intent": "create_draft", "customer": "Panha", "lang": "mixed"},

    # =========================================================================
    # 2. UPDATE_DRAFT (30 examples)
    # =========================================================================
    {"text": "actually make it 4 monitors", "intent": "update_draft", "lang": "en"},
    {"text": "change to 3 chairs", "intent": "update_draft", "lang": "en"},
    {"text": "add 1 keyboard for $25", "intent": "update_draft", "lang": "en"},
    {"text": "change unit price to $400", "intent": "update_draft", "lang": "en"},
    {"text": "make it 5 bags of coffee", "intent": "update_draft", "lang": "en"},
    {"text": "add delivery fee of $5", "intent": "update_draft", "lang": "en"},
    {"text": "change quantity to 10", "intent": "update_draft", "lang": "en"},
    {"text": "actually make it 2 laptops", "intent": "update_draft", "lang": "en"},
    {"text": "update price to $45", "intent": "update_draft", "lang": "en"},
    {"text": "add 2 mousepads for $10 each", "intent": "update_draft", "lang": "en"},

    {"text": "កែជា ៤ គ្រឿងវិញ", "intent": "update_draft", "lang": "km"},
    {"text": "ប្តូរចំនួនទៅ ៣ វិញ", "intent": "update_draft", "lang": "km"},
    {"text": "ថែមក្តារចុច ១ តម្លៃ ២៥ ដុល្លារ", "intent": "update_draft", "lang": "km"},
    {"text": "កែតម្លៃជា ៤០០$", "intent": "update_draft", "lang": "km"},
    {"text": "ប្តូរជា ៥ ថង់វិញ", "intent": "update_draft", "lang": "km"},
    {"text": "ថែមថ្លៃដឹកជញ្ជូន ៥ ដុល្លារ", "intent": "update_draft", "lang": "km"},
    {"text": "កែចំនួនជា ១០", "intent": "update_draft", "lang": "km"},
    {"text": "ប្តូរទៅ ២ គ្រឿងវិញ", "intent": "update_draft", "lang": "km"},
    {"text": "កែតម្លៃទៅ ៤៥$", "intent": "update_draft", "lang": "km"},
    {"text": "ថែមទ្រនាប់កណ្ដុរ ២ តម្លៃ ១០$", "intent": "update_draft", "lang": "km"},

    {"text": "actually make it 4 monitors វិញ", "intent": "update_draft", "lang": "mixed"},
    {"text": "កែជា 3 monitors", "intent": "update_draft", "lang": "mixed"},
    {"text": "add 1 keyboard ថ្លៃ $25", "intent": "update_draft", "lang": "mixed"},
    {"text": "change price to $400 វិញ", "intent": "update_draft", "lang": "mixed"},
    {"text": "make it 5 bags វិញ", "intent": "update_draft", "lang": "mixed"},
    {"text": "ថែម delivery $5", "intent": "update_draft", "lang": "mixed"},
    {"text": "change quantity ជា 10", "intent": "update_draft", "lang": "mixed"},
    {"text": "actually make it 2 laptops វិញ", "intent": "update_draft", "lang": "mixed"},
    {"text": "កែ price ទៅ $45", "intent": "update_draft", "lang": "mixed"},
    {"text": "add 2 mouse pads ថ្លៃ $10", "intent": "update_draft", "lang": "mixed"},

    # =========================================================================
    # 3. CONFIRM (20 examples)
    # =========================================================================
    {"text": "confirm", "intent": "confirm", "lang": "en"},
    {"text": "looks good", "intent": "confirm", "lang": "en"},
    {"text": "send it", "intent": "confirm", "lang": "en"},
    {"text": "yes", "intent": "confirm", "lang": "en"},
    {"text": "approved", "intent": "confirm", "lang": "en"},
    {"text": "correct", "intent": "confirm", "lang": "en"},
    {"text": "proceed", "intent": "confirm", "lang": "en"},
    {"text": "yes please confirm", "intent": "confirm", "lang": "en"},

    {"text": "យល់ព្រម", "intent": "confirm", "lang": "km"},
    {"text": "ផ្ញើទៅ", "intent": "confirm", "lang": "km"},
    {"text": "ត្រឹមត្រូវហើយ", "intent": "confirm", "lang": "km"},
    {"text": "បាទ យល់ព្រម", "intent": "confirm", "lang": "km"},
    {"text": "ចាស ត្រឹមត្រូវ", "intent": "confirm", "lang": "km"},
    {"text": "យល់ព្រមផ្ញើ", "intent": "confirm", "lang": "km"},
    {"text": "ត្រឹមត្រូវ", "intent": "confirm", "lang": "km"},
    {"text": "បញ្ជាក់", "intent": "confirm", "lang": "km"},

    {"text": "ok confirm", "intent": "confirm", "lang": "mixed"},
    {"text": "yes ផ្ញើទៅ", "intent": "confirm", "lang": "mixed"},
    {"text": "looks good បញ្ជាក់មក", "intent": "confirm", "lang": "mixed"},
    {"text": "ok យល់ព្រម", "intent": "confirm", "lang": "mixed"},

    # =========================================================================
    # 4. CANCEL (15 examples)
    # =========================================================================
    {"text": "cancel", "intent": "cancel", "lang": "en"},
    {"text": "nevermind", "intent": "cancel", "lang": "en"},
    {"text": "discard", "intent": "cancel", "lang": "en"},
    {"text": "delete this draft", "intent": "cancel", "lang": "en"},
    {"text": "stop", "intent": "cancel", "lang": "en"},
    {"text": "cancel invoice", "intent": "cancel", "lang": "en"},

    {"text": "បោះបង់", "intent": "cancel", "lang": "km"},
    {"text": "លុបចោល", "intent": "cancel", "lang": "km"},
    {"text": "ឈប់", "intent": "cancel", "lang": "km"},
    {"text": "មិនបាច់ទេ", "intent": "cancel", "lang": "km"},
    {"text": "លុបព្រាងនេះចោល", "intent": "cancel", "lang": "km"},
    {"text": "បោះបង់វិក្កយបត្រ", "intent": "cancel", "lang": "km"},

    {"text": "cancel ចោលទៅ", "intent": "cancel", "lang": "mixed"},
    {"text": "stop ឈប់សិន", "intent": "cancel", "lang": "mixed"},
    {"text": "nevermind លុបចោលវិញ", "intent": "cancel", "lang": "mixed"},

    # =========================================================================
    # 5. SEARCH (20 examples)
    # =========================================================================
    {"text": "find Dara invoice", "intent": "search", "lang": "en"},
    {"text": "show my invoices this week", "intent": "search", "lang": "en"},
    {"text": "search for Sokha", "intent": "search", "lang": "en"},
    {"text": "list all unpaid invoices", "intent": "search", "lang": "en"},
    {"text": "search INV-000001", "intent": "search", "lang": "en"},
    {"text": "find invoices for Angkor Mart", "intent": "search", "lang": "en"},
    {"text": "show history", "intent": "search", "lang": "en"},
    {"text": "search paid invoices", "intent": "search", "lang": "en"},

    {"text": "ស្វែងរក Dara", "intent": "search", "lang": "km"},
    {"text": "រកមើលវិក្កយបត្រ សុខា", "intent": "search", "lang": "km"},
    {"text": "បង្ហាញវិក្កយបត្រសប្តាហ៍នេះ", "intent": "search", "lang": "km"},
    {"text": "រកមើលវិក្កយបត្រមិនទាន់បង់", "intent": "search", "lang": "km"},
    {"text": "ស្វែងរក INV-000001", "intent": "search", "lang": "km"},
    {"text": "បង្ហាញប្រវត្តិវិក្កយបត្រ", "intent": "search", "lang": "km"},
    {"text": "ស្វែងរកអតិថិជន បុប្ផា", "intent": "search", "lang": "km"},
    {"text": "រកមើលវិក្កយបត្រដែលបានបង់", "intent": "search", "lang": "km"},

    {"text": "find វិក្កយបត្រ Dara", "intent": "search", "lang": "mixed"},
    {"text": "ស្វែងរក invoice Sokha", "intent": "search", "lang": "mixed"},
    {"text": "show invoices សប្តាហ៍នេះ", "intent": "search", "lang": "mixed"},
    {"text": "search វិក្កយបត្រ Bopha", "intent": "search", "lang": "mixed"},

    # =========================================================================
    # 6. SELECT_CUSTOMER (15 examples)
    # =========================================================================
    {"text": "choose 1", "intent": "select_customer", "lang": "en"},
    {"text": "select 2", "intent": "select_customer", "lang": "en"},
    {"text": "pick customer 1", "intent": "select_customer", "lang": "en"},
    {"text": "customer 2", "intent": "select_customer", "lang": "en"},
    {"text": "select Dara Logistics", "intent": "select_customer", "lang": "en"},

    {"text": "ជ្រើសរើស ១", "intent": "select_customer", "lang": "km"},
    {"text": "រើសលេខ ២", "intent": "select_customer", "lang": "km"},
    {"text": "ជ្រើសរើសអតិថិជន ១", "intent": "select_customer", "lang": "km"},
    {"text": "យកលេខ ២", "intent": "select_customer", "lang": "km"},
    {"text": "ជ្រើសរើស សុខា ត្រេឌីង", "intent": "select_customer", "lang": "km"},

    {"text": "select លេខ 1", "intent": "select_customer", "lang": "mixed"},
    {"text": "choose customer 2 វិញ", "intent": "select_customer", "lang": "mixed"},
    {"text": "យក option 1", "intent": "select_customer", "lang": "mixed"},
    {"text": "pick លេខ 2", "intent": "select_customer", "lang": "mixed"},
    {"text": "select អតិថិជន 1", "intent": "select_customer", "lang": "mixed"},

    # =========================================================================
    # 7. CLARIFY_NEEDED (15 examples)
    # =========================================================================
    {"text": "bill someone $50", "intent": "clarify_needed", "lang": "en"},
    {"text": "invoice Sokha", "intent": "clarify_needed", "lang": "en"},
    {"text": "create invoice", "intent": "clarify_needed", "lang": "en"},
    {"text": "send bill for 100", "intent": "clarify_needed", "lang": "en"},
    {"text": "bill $20", "intent": "clarify_needed", "lang": "en"},

    {"text": "គិតលុយ ៥០$", "intent": "clarify_needed", "lang": "km"},
    {"text": "ធ្វើវិក្កយបត្រឱ្យ សុខា", "intent": "clarify_needed", "lang": "km"},
    {"text": "ចេញវិក្កយបត្រ", "intent": "clarify_needed", "lang": "km"},
    {"text": "គិតលុយថ្លៃទំនិញ", "intent": "clarify_needed", "lang": "km"},
    {"text": "ធ្វើ invoice", "intent": "clarify_needed", "lang": "km"},

    {"text": "invoice Dara", "intent": "clarify_needed", "lang": "mixed"},
    {"text": "bill ឲ្យគាត់ $50", "intent": "clarify_needed", "lang": "mixed"},
    {"text": "ធ្វើ invoice $100", "intent": "clarify_needed", "lang": "mixed"},
    {"text": "create bill ឱ្យគេ", "intent": "clarify_needed", "lang": "mixed"},
    {"text": "invoice 2 monitors", "intent": "clarify_needed", "lang": "mixed"},
]


def seed_dataset(output_path=OUTPUT_PATH):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for item in DATASET_SAMPLES:
            record = {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "text": item["text"],
                "intent": item["intent"],
                "confidence": 0.95,
                "customer_name": item.get("customer"),
                "items": [],
                "language": item.get("lang", "en"),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    print(f"Successfully seeded {count} high-quality annotated examples into {output_path}!")


if __name__ == "__main__":
    seed_dataset()

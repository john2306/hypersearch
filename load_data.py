import json
import requests

base_url = "http://127.0.0.1:8000/"


with open("faqs.json", "r", encoding="utf-8") as f:
    faqs_data = json.load(f)
    faqs_data_formatted = [
        {
            "title": faq["title"],
            "content": faq["body"],
            "content_type": 'text',
            "source_id": str(faq["id"])
        }
        for faq in faqs_data
    ]
    response = requests.post(f"{base_url}/add_knowledge", json=[faqs_data_formatted[0]])
    print(f"Response for FAQs: {response.status_code}")

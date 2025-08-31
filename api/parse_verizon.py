import fitz  # PyMuPDF
from collections import defaultdict
import os
import re
from glob import glob
from datetime import datetime
from sib_api_v3_sdk import Configuration, ApiClient, TransactionalEmailsApi, SendSmtpEmail
from sib_api_v3_sdk.rest import ApiException
from dotenv import load_dotenv

load_dotenv()

# Embedded mapping
line_to_person = {
    "Nancy Siegel": "Savti",
    "David J Siegel": "Papa",
    "Elana Siegel": "New Roc Siegels",
    "Tova Niderberg": "Riverdale Siegels",
    "Tova Niderberg Watch": "Riverdale Siegels",
    "David Siegel 1": "New Roc Siegels",
    "Emmy": "Simchis",
    "Caleb Siegel": "Riverdale Siegels",
    "Simmy Siegel": "New Roc Siegels",
    "Penina Simchi": "Simchis",
    "David Siegel 2": "Simchis",
}

email_list = [
    "caleb.siegel@gmail.com",
    "elana.siegel@gmail.com",
    "penina.siegel@gmail.com",
    "nansiegel@gmail.com",
    "djs.siegel@gmail.com",
]

def get_latest_mybill_pdf(folder="./verizon-bills"):
    pdf_files = glob(os.path.join(folder, "MyBill_*.pdf"))
    dated_files = []

    for file in pdf_files:
        match = re.search(r"MyBill_(\d{2})\.(\d{2})\.(\d{4})\.pdf", os.path.basename(file))
        if match:
            mm, dd, yyyy = match.groups()
            try:
                file_date = datetime.strptime(f"{yyyy}-{mm}-{dd}", "%Y-%m-%d")
                dated_files.append((file_date, file))
            except ValueError:
                continue

    if not dated_files:
        raise FileNotFoundError("No correctly formatted MyBill PDFs found.")

    latest_file = max(dated_files, key=lambda x: x[0])[1]
    return latest_file

def extract_charges_from_pdf(pdf_path):
    print(f'Extracting charges from {pdf_path}')
    doc = fitz.open("pdf", pdf_path)
    
    account_wide_value = 0.0
    line_details = {}

    phone_pattern = r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'

    for page in doc:
        lines = page.get_text("text").split("\n")

        for i in range(1, len(lines) - 2):  # need room for i+2
            line = lines[i].strip()

            if line.startswith("$") or re.match(r"^-?\$\d", line):
                prev_line = lines[i - 1].strip()
                try:
                    amount = float(line.replace("$", "").replace(",", ""))

                    if prev_line == "Account-wide charges & credits":
                        account_wide_value = amount
                    else:
                        # Only consider if i+2 has a phone number
                        candidate = lines[i + 2].strip()
                        phone_match = re.search(phone_pattern, candidate)

                        if phone_match:
                            number = phone_match.group()
                            device = lines[i + 1].strip()

                            # Create a unique key using name + device + number
                            unique_key = f"{prev_line} | {device} | {number}"

                            line_details[unique_key] = {
                                "name": prev_line,
                                "device": device,
                                "number": number,
                                "charge": amount
                            }

                except ValueError:
                    continue

    return account_wide_value, line_details

def group_by_person(line_charges):
    person_totals = defaultdict(float)
    for line, amount in line_charges.items():
        person = line_to_person.get(line, "Unknown")
        person_totals[person] += amount
    return dict(person_totals)

def generate_messages(person_totals, zelle_email="djs.siegel@email.com"):
    messages = ""
    for person, amount in person_totals.items():
        # Format the amount to two decimal places for currency
        messages += f"{person}: ${amount:.2f}<br/>"
    print(messages)
    return messages

def adjust_for_smartwatch_discount(person_totals):
    if "New Roc Siegels" in person_totals and "Riverdale Siegels" in person_totals:
        person_totals["New Roc Siegels"] -= 7
        person_totals["Riverdale Siegels"] += 7

def send_email(person_totals, custom_email_list=None, sender_email=None):
    breakdown_message = generate_messages(person_totals)
    total_cost = sum(person_totals.values())
    
    # Configure API key authorization
    configuration = Configuration()
    configuration.api_key['api-key'] = os.getenv('SENDINBLUE_API_KEY')

    api_instance = TransactionalEmailsApi(ApiClient(configuration))

    html_content = f"""
    Hey family!<br/><br/>
    
    This month's verizon bill is ${total_cost}.<br/><br/>
    
    Here's the breakdown: <br/>
    {breakdown_message}<br/>
        
    Please Zelle Papa.<br/><br/>

    Pleasure doing business with ya.
    """

    # Use custom email list if provided, otherwise use default
    email_list_to_use = custom_email_list if custom_email_list is not None else email_list
    
    # Use sender email if provided, otherwise use default
    sender_email_to_use = sender_email if sender_email is not None else "caleb.siegel@gmail.com"
    
    # Clean and validate email addresses
    
    # Clean and validate email addresses
    cleaned_emails = []
    for email in email_list_to_use:
        # Remove trailing commas and whitespace
        cleaned_email = email.strip().rstrip(',')
        # Basic email validation
        if '@' in cleaned_email and '.' in cleaned_email and len(cleaned_email) > 5:
            cleaned_emails.append(cleaned_email)
        else:
            print(f"Invalid email address skipped: {email}")
    
    to_list = [{"email": email} for email in cleaned_emails]
    print(f"Cleaned email list: {to_list}")

    send_smtp_email = SendSmtpEmail(
        to=to_list,
        sender={"name": "Verizon Monthly Phone Cost", "email": sender_email_to_use},
        subject=f"Monthly Verizon Bill",
        html_content=html_content
    )

    try:
        api_response = api_instance.send_transac_email(send_smtp_email)
        print(f"Email sent successfully")
    except ApiException as e:
        print(f"Error sending email: {e}")
        raise e

if __name__ == "__main__":
    pdf_path = get_latest_mybill_pdf("verizon-bills")
    charges, account_wide_value = extract_charges_from_pdf(pdf_path)
    person_totals = group_by_person(charges)
    unique_people = set(line_to_person.values())
    if unique_people and account_wide_value != 0.0:
        per_person_share = account_wide_value / len(unique_people)
        for person in unique_people:
            person_totals[person] = person_totals.get(person, 0.0) + per_person_share
    else:
        print("No account-wide charges & credits to distribute or no unique people found.")
    adjust_for_smartwatch_discount(person_totals)
    
    send_email(person_totals)
    
    print(f'Total: ${sum(person_totals.values())}')

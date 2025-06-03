import yaml
import logging
import os
from email_client import EmailClient
from extractor import ContactExtractor
from filters import EmailFilter
from storage import StorageManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

def load_accounts(filter_tags=None):
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        accounts_path = os.path.join(base_dir, 'config', 'accounts.yaml')
        with open(accounts_path, 'r') as file:
            all_accounts = yaml.safe_load(file)['accounts']
            filtered_accounts = [
                acc for acc in all_accounts
                if acc.get('active', True) and
                (not filter_tags or any(tag in acc.get('tags', []) for tag in filter_tags))
            ]
            return filtered_accounts
    except Exception as e:
        logging.error(f"Error loading accounts: {str(e)}")
        return []

def process_account(account, storage, extractor, email_filter, batch_size=150):
    email_client = EmailClient(account)
    if not email_client.connect():
        logging.error(f"Failed to connect to {account['email']}")
        return

    # Load previously saved emails for this account (from CSV)
    seen_emails = set()
    contacts_file = os.path.join(storage.contacts_dir, f"{account['email'].replace('@', '_at_')}.csv")
    if os.path.exists(contacts_file):
        import csv
        with open(contacts_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('email'):
                    seen_emails.add(row['email'].strip().lower())

    try:
        last_run = storage.load_last_run()
        account_last_run = last_run.get(account['email'], {})
        last_uid = account_last_run.get('last_uid')

        while True:
            emails = email_client.fetch_emails(since_uid=last_uid, batch_size=batch_size)
            if not emails:
                break

            recruiter_emails = email_filter.filter_recruiter_emails(emails, extractor)
            contacts = []
            for email_data in recruiter_emails:
                try:
                    contact = extractor.extract_contacts(email_data['message'])
                    email_val = contact.get('email')
                    if email_val:
                        email_val = email_val.strip().lower()
                        if email_val not in seen_emails:
                            contacts.append(contact)
                            seen_emails.add(email_val)
                        else:
                            logging.info(f"Duplicate email across batches, not saving: {email_val}")
                except Exception as e:
                    continue

            if contacts:
                storage.save_contacts(account['email'], contacts)

            # Update last_uid for next batch
            max_uid = max(int(email['uid']) for email in emails)
            storage.save_last_run(account['email'], str(max_uid))
            last_uid = str(max_uid)

            # If less than batch_size, we're done
            if len(emails) < batch_size:
                break

    except Exception as e:
        logging.error(f"Error processing account {account['email']}: {str(e)}")
    finally:
        email_client.disconnect()

def deduplicate_contacts(contacts):
    seen = set()
    unique_contacts = []
    for contact in contacts:
        key = (contact['email'], contact.get('company', ''))
        if key not in seen:
            seen.add(key)
            unique_contacts.append(contact)
        else:
            logging.info(f"Duplicate contact, not saving: {contact['email']}")
    return unique_contacts

def main():
    logging.info("Starting email contact extraction")

    accounts = load_accounts(filter_tags=["job_search"])

    if not accounts:
        logging.error("No active accounts found matching criteria")
        return

    storage = StorageManager()
    extractor = ContactExtractor()
    email_filter = EmailFilter()

    for account in accounts:
        logging.info(f"Processing account: {account['email']}")
        process_account(account, storage, extractor, email_filter, batch_size=150)

    logging.info("Email contact extraction completed")

if __name__ == "__main__":
    main()
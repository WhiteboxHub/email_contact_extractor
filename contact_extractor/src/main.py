import yaml
import logging
import os
from email_client import EmailClient
from extractor import ContactExtractor
from filters import EmailFilter
from storage import StorageManager

# Configure logging
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

def process_account(account, storage, extractor, email_filter, batch_size=100):
    email_client = EmailClient(account)
    if not email_client.connect():
        logging.error(f"Failed to connect to {account['email']}")
        return

    try:
        last_run = storage.load_last_run()
        account_last_run = last_run.get(account['email'], {})
        last_uid = account_last_run.get('last_uid')

        logging.info(f"Starting batch processing for {account['email']} (last_uid={last_uid})")
        start_index = 0
        max_uid_seen = int(last_uid) if last_uid else 0
        total_extracted = 0

        while True:
            emails, next_start_index = email_client.fetch_emails(
                since_uid=last_uid, batch_size=batch_size, start_index=start_index
            )
            if not emails:
                logging.info(f"No more emails to process for {account['email']} (start_index={start_index})")
                break

            logging.info(f"Fetched {len(emails)} emails for {account['email']} (batch {start_index // batch_size + 1})")

            recruiter_emails = email_filter.filter_recruiter_emails(emails, extractor)
            logging.info(f"Filtered {len(recruiter_emails)} recruiter emails in this batch for {account['email']}")

            contacts = []
            for email_data in recruiter_emails:
                try:
                    contact = extractor.extract_contacts(email_data['message'])
                    if contact.get('email'):
                        logging.info(f"Extracted contact: {contact}")
                        contacts.append(contact)
                    else:
                        logging.info(f"Skipped non-recruiter email: {email_data['message'].get('From')}")
                except Exception as e:
                    logging.error(f"Error extracting contact: {str(e)}")
                    continue

            contacts = deduplicate_contacts(contacts)
            if contacts:
                logging.info(f"Extracted {len(contacts)} contacts in this batch for {account['email']}")
                storage.save_contacts(account['email'], contacts)
                total_extracted += len(contacts)

            # Update max_uid_seen
            batch_uids = [int(email['uid']) for email in emails if email.get('uid')]
            if batch_uids:
                max_uid_seen = max(max_uid_seen, max(batch_uids))
                storage.save_last_run(account['email'], str(max_uid_seen))
                logging.info(f"Updated last_uid for {account['email']} to {max_uid_seen}")

            if not next_start_index:
                break
            start_index = next_start_index

        logging.info(f"Completed processing for {account['email']}. Total contacts extracted: {total_extracted}")

    except Exception as e:
        logging.error(f"Error processing account {account['email']}: {str(e)}")
    finally:
        email_client.disconnect()
        logging.info(f"Disconnected from {account['email']}")

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
    # accounts = load_accounts()  # Uncomment to process all active accounts

    if not accounts:
        logging.error("No active accounts found matching criteria")
        return

    storage = StorageManager()
    extractor = ContactExtractor()
    email_filter = EmailFilter()

    for account in accounts:
        logging.info(f"Processing account: {account['email']}")
        process_account(account, storage, extractor, email_filter)

    logging.info("Email contact extraction completed")

if __name__ == "__main__":
    main()
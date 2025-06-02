import csv
import json
import os
from datetime import datetime
import logging

class StorageManager:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # Compute absolute paths for data directory and files
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.path.join(self.base_dir, 'data')
        self.contacts_dir = os.path.join(self.data_dir, 'extracted_contacts')
        self.last_run_path = os.path.join(self.data_dir, 'last_run.json')
        # Ensure data directory exists, but do not create extracted_contacts here
        os.makedirs(self.data_dir, exist_ok=True)

    def save_contacts(self, email_account: str, contacts: list):
        """Save contacts to CSV file"""
        if not contacts:
            return

        # Ensure extracted_contacts directory exists only if saving contacts
        if not os.path.exists(self.contacts_dir):
            os.makedirs(self.contacts_dir, exist_ok=True)

        filename = os.path.join(
            self.contacts_dir, f"{email_account.replace('@', '_at_')}.csv"
        )
        file_exists = os.path.isfile(filename)
        
        try:
            with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    'name', 'email', 'phone', 'company', 
                    'website', 'source', 'linkedin_url', 'extracted_date'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                
                for contact in contacts:
                    if contact.get('phone'):
                        contact['phone'] = "'" + contact['phone']
                    contact['extracted_date'] = datetime.now().isoformat()
                    writer.writerow(contact)
        except Exception as e:
            self.logger.error(f"Error saving contacts: {str(e)}")

    def load_last_run(self):
        """Load last run information"""
        try:
            if os.path.exists(self.last_run_path):
                with open(self.last_run_path, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            self.logger.error(f"Error loading last run data: {str(e)}")
            return {}

    def save_last_run(self, email_account: str, last_uid: str):
        """Save last processed email UID"""
        try:
            data = self.load_last_run()
            data[email_account] = {
                'last_uid': last_uid,
                'last_run': datetime.now().isoformat()
            }
            
            with open(self.last_run_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving last run data: {str(e)}")
import csv
import json
import os
from datetime import datetime
import logging
import re

class StorageManager:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.path.join(self.base_dir, 'data')
        self.contacts_dir = os.path.join(self.data_dir, 'extracted_contacts')
        self.last_run_path = os.path.join(self.data_dir, 'last_run.json')
        os.makedirs(self.data_dir, exist_ok=True)

    def _is_valid_email(self, email):
        if not email:
            return False
        pattern = r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)"
        return re.match(pattern, email) is not None

    def _is_valid_phone(self, phone):
        if not phone:
            return False
        # Accepts numbers, spaces, dashes, parentheses, plus, min 7 digits
        digits = re.sub(r'\D', '', phone)
        return len(digits) >= 7

    def _is_valid_url(self, url):
        if not url:
            return False
        # Simple URL validation
        pattern = r"^(https?://)?([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/.*)?$"
        return re.match(pattern, url) is not None

    def _is_valid_name(self, name):
        if not name:
            return False
        # Name should be at least 2 characters, not all digits, not all special chars
        if len(name.strip()) < 2:
            return False
        if re.match(r'^[\W_]+$', name):
            return False
        if re.match(r'^\d+$', name):
            return False
        return True

    def _is_valid_company(self, company):
        if not company:
            return False
        # Company name should be at least 2 characters, not all digits or special chars
        if len(company.strip()) < 2:
            return False
        if re.match(r'^[\W_]+$', company):
            return False
        if re.match(r'^\d+$', company):
            return False
        return True

    def save_contacts(self, email_account: str, contacts: list):
        """Save contacts to CSV file"""
        if not contacts:
            return

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
                    # Validate each field, set to blank if invalid
                    row = {}
                    # Email: must be valid and not a linkedin.com address
                    email_val = contact.get('email', '')
                    if not self._is_valid_email(email_val) or ('linkedin.com' in email_val if email_val else False):
                        row['email'] = ''
                    else:
                        row['email'] = email_val

                    # Name
                    name_val = contact.get('name', '')
                    row['name'] = name_val if self._is_valid_name(name_val) else ''

                    # Phone
                    phone_val = contact.get('phone', '')
                    if self._is_valid_phone(phone_val):
                        row['phone'] = "'" + phone_val
                    else:
                        row['phone'] = ''

                    # Company
                    company_val = contact.get('company', '')
                    row['company'] = company_val if self._is_valid_company(company_val) else ''

                    # Website
                    website_val = contact.get('website', '')
                    row['website'] = website_val if self._is_valid_url(website_val) else ''

                    # Source
                    source_val = contact.get('source', '')
                    row['source'] = source_val if source_val else ''

                    # LinkedIn URL
                    linkedin_val = contact.get('linkedin_url', '')
                    row['linkedin_url'] = linkedin_val if self._is_valid_url(linkedin_val) else ''

                    # Extracted date
                    row['extracted_date'] = datetime.now().isoformat()

                    # Only write if email is valid and not blank
                    if not row['email']:
                        continue

                    writer.writerow(row)
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
import re
import logging
from email.utils import parseaddr
from urllib.parse import urlparse
import yaml
import os
from email_client import EmailClient

class ContactExtractor:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.rules = self._load_rules()

    def _load_rules(self):
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            rules_path = os.path.join(base_dir, 'config', 'rules.yaml')
            with open(rules_path, 'r') as file:
                return yaml.safe_load(file)
        except Exception as e:
            self.logger.error(f"Error loading rules: {str(e)}")
            return {}

    def is_recruiter_email(self, email_message):
        subject = self._get_email_subject(email_message)
        from_email = self._get_sender_email(email_message)
        sender_name = parseaddr(email_message.get('From', ''))[0]

        # Check subject and sender name for recruiter keywords
        subject_match = any(
            keyword.lower() in subject.lower() 
            for keyword in self.rules.get('recruiter_keywords', [])
        )
        name_match = any(
            keyword.lower() in sender_name.lower()
            for keyword in self.rules.get('recruiter_keywords', [])
        )

        # Check sender domain against domain strategy
        domain = from_email.split('@')[-1].lower() if '@' in from_email else ''
        domain_valid = self._validate_domain(domain)

        # Exclude generic job board/system emails
        generic_patterns = [
            r'jobs-listings@linkedin\.com',
            r'newsletters-noreply@linkedin\.cc',
            r'noreply@.*',
            r'.*no-reply.*',
            r'do-not-reply@.*',
            r'notifications@.*',
            r'jobs@.*',
            r'info@.*'
        ]
        for pattern in generic_patterns:
            if re.fullmatch(pattern, from_email):
                self.logger.info(f"Skipping generic sender: {from_email}")
                return False

        return (subject_match or name_match) and domain_valid

    def _validate_domain(self, domain):
        if not domain:
            return False

        strategy = self.rules.get('domain_strategy', 'hybrid')

        # Check always_blacklist first
        for pattern in self.rules.get('always_blacklist', []):
            if re.fullmatch(pattern, domain):
                return False

        # Check always_whitelist
        for pattern in self.rules.get('always_whitelist', []):
            if re.fullmatch(pattern, domain):
                return True

        # Apply selected strategy
        if strategy == 'whitelist':
            return any(
                re.fullmatch(pattern, domain)
                for pattern in self.rules.get('whitelist_domains', [])
            )
        elif strategy == 'blacklist':
            return not any(
                re.fullmatch(pattern, domain)
                for pattern in self.rules.get('blacklist_patterns', [])
            )
        else:  # hybrid - must be in whitelist AND not in blacklist
            whitelisted = any(
                re.fullmatch(pattern, domain)
                for pattern in self.rules.get('whitelist_domains', [])
            )
            blacklisted = any(
                re.fullmatch(pattern, domain)
                for pattern in self.rules.get('blacklist_patterns', [])
            )
            return whitelisted and not blacklisted

    def extract_contacts(self, email_message):
        from_header = email_message.get('From', '')
        sender_name, sender_email = parseaddr(from_header)
        
        # Clean the sender name
        sender_name = ' '.join(
            part.capitalize() for part in re.split(r'[^a-zA-Z]', sender_name) if part
        )
        
        # Get email body for further extraction
        body = self._get_email_body(email_message)
        
        # Extract additional info from body/signature
        phone = self._extract_phone(body)
        company = self._extract_company(body, sender_email)
        website = self._extract_website(body)
        linkedin_url = self._extract_linkedin(body)
        
        return {
            'name': sender_name or None,
            'email': sender_email.lower() if sender_email else None,
            'phone': phone,
            'company': company,
            'website': website,
            'source': 'email',
            'linkedin_url': linkedin_url
        }

    def _get_email_subject(self, email_message):
        subject = email_message.get('Subject', '')
        return EmailClient.clean_text(subject)

    def _get_sender_email(self, email_message):
        from_header = email_message.get('From', '')
        _, sender_email = parseaddr(from_header)
        return sender_email.lower()

    def _get_email_body(self, email_message):
        body = ""
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                if content_type == 'text/plain':
                    body += part.get_payload(decode=True).decode('utf-8', errors='ignore')
        else:
            body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
        return body

    def _extract_phone(self, text):
        for pattern in self.rules.get('signature_patterns', {}).get('phone', []):
            for match in re.finditer(pattern, text):
                phone = match.group(0)
                digits = re.sub(r'\D', '', phone)
                if 10 <= len(digits) <= 15:  # Acceptable phone number length
                    return phone
        return None

    def _extract_company(self, text, sender_email):
        # First try to find company name in signature
        company_patterns = [
            r'at\s+([A-Z][a-zA-Z\s&]+)',
            r'([A-Z][a-zA-Z\s&]+)\s*Inc',
            r'([A-Z][a-zA-Z\s&]+)\s*LLC',
        ]
        
        for pattern in company_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        
        # Fallback to domain name
        if sender_email and '@' in sender_email:
            domain = sender_email.split('@')[1]
            return domain.split('.')[0].capitalize()
        
        return None

    def _extract_website(self, text):
        url_pattern = r'https?://[^\s/$.?#].[^\s]*'
        matches = re.findall(url_pattern, text)
        for url in matches:
            parsed = urlparse(url)
            if parsed.netloc and 'linkedin.com' not in parsed.netloc:
                return url
        return None

    def _extract_linkedin(self, text):
        for pattern in self.rules.get('signature_patterns', {}).get('linkedin', []):
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None
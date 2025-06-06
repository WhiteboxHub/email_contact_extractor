import re
import logging
from email.utils import parseaddr
from urllib.parse import urlparse
import yaml
import os
from email_client import EmailClient
import phonenumbers

class ContactExtractor:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.rules = self._load_rules()

    def _load_rules(self):
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            rules_path = os.path.join(base_dir, 'config', 'rules.yaml')
            with open(rules_path, 'r') as file:
                rules = yaml.safe_load(file)
                self.logger.info(f"Loaded rules: {rules.keys()}")
                return rules
        except Exception as e:
            self.logger.error(f"Error loading rules: {str(e)}")
            return {}

    def is_recruiter_email(self, email_message):
        subject = self._get_email_subject(email_message)
        from_email = self._get_sender_email(email_message)
        sender_name = parseaddr(email_message.get('From', ''))[0]
        body = self._get_email_body(email_message)

        # Defensive: always use a list
        recruiter_keywords = self.rules.get('recruiter_keywords') or []
        if not recruiter_keywords:
            self.logger.error("No recruiter_keywords found in rules. Please check rules.yaml.")
            return False

        subject_match = any(keyword.lower() in subject.lower() for keyword in recruiter_keywords)
        name_match = any(keyword.lower() in sender_name.lower() for keyword in recruiter_keywords)
        email_match = any(keyword.lower() in from_email.lower() for keyword in recruiter_keywords)
        body_match = any(keyword.lower() in body.lower() for keyword in recruiter_keywords)

        # Check sender domain against domain strategy
        domain = from_email.split('@')[-1].lower() if '@' in from_email else ''
        domain_valid = self._validate_domain(domain)

        # Exclude generic job board/system emails
        # Use always_blacklist patterns from rules.yaml for generic sender exclusion
        generic_patterns = self.rules.get('always_blacklist', [])
        for pattern in generic_patterns:
            if re.fullmatch(pattern, from_email):
                self.logger.info(f"Skipping generic sender: {from_email} (pattern: {pattern})")
                return False

        if not (subject_match or name_match or email_match or body_match):
            self.logger.info(f"Email from {from_email} skipped: no recruiter keywords in subject, sender name, sender email, or body.")
        if not domain_valid:
            self.logger.info(f"Email from {from_email} skipped: domain '{domain}' not valid per rules.")

        return (subject_match or name_match or email_match or body_match) and domain_valid

    def _validate_domain(self, domain):
        if not domain:
            return False

        strategy = self.rules.get('domain_strategy', 'hybrid')

        # Check always_blacklist first
        for pattern in self.rules.get('always_blacklist') or []:
            if re.fullmatch(pattern, domain):
                return False

        # Check always_whitelist
        for pattern in self.rules.get('always_whitelist') or []:
            if re.fullmatch(pattern, domain):
                return True

        # Apply selected strategy
        if strategy == 'whitelist':
            return any(
                re.fullmatch(pattern, domain)
                for pattern in self.rules.get('whitelist_domains') or []
            )
        elif strategy == 'blacklist':
            return not any(
                re.fullmatch(pattern, domain)
                for pattern in self.rules.get('blacklist_patterns') or []
            )
        else:  # hybrid - must be in whitelist AND not in blacklist
            whitelisted = any(
                re.fullmatch(pattern, domain)
                for pattern in self.rules.get('whitelist_domains') or []
            )
            blacklisted = any(
                re.fullmatch(pattern, domain)
                for pattern in self.rules.get('blacklist_patterns') or []
            )
            return whitelisted and not blacklisted

    def extract_contacts(self, email_message, source_email=None):
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
        linkedin_id = self._extract_linkedin(body)
        return {
            'name': sender_name or None,
            'email': sender_email.lower() if sender_email else None,
            'phone': phone,
            'company': company,
            'website': website,
            'source': source_email.lower() if source_email else None,
            'linkedin_id': linkedin_id
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
        for pattern in self.rules.get('signature_patterns', {}).get('phone') or []:
            for match in re.finditer(pattern, text):
                phone = match.group(0)
                # Try to parse and format the phone number
                try:
                    # You can specify a default region, e.g., 'US' or 'IN'
                    parsed = phonenumbers.parse(phone, "US")
                    if phonenumbers.is_valid_number(parsed):
                        # Format to E.164: +1234567890
                        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
                except phonenumbers.NumberParseException:
                    continue
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
        # Look for LinkedIn URLs in the text
        linkedin_pattern = r'https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/([a-zA-Z0-9\-_]+)'
        match = re.search(linkedin_pattern, text)
        if match:
            return match.group(1)  # This is the LinkedIn ID
        # Fallback to previous patterns if needed
        for pattern in self.rules.get('signature_patterns', {}).get('linkedin', []):
            match = re.search(pattern, text)
            if match:
                # Try to extract the ID from the matched URL
                id_match = re.search(r'linkedin\.com/in/([a-zA-Z0-9\-_]+)', match.group(0))
                if id_match:
                    return id_match.group(1)
        return None
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
        self.account_blacklist_patterns = self._load_account_blacklist_patterns()

    def _load_rules(self):
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            rules_path = os.path.join(base_dir, 'config', 'rules.yaml')
            with open(rules_path, 'r') as file:
                return yaml.safe_load(file)
        except Exception as e:
            self.logger.error(f"Error loading rules: {str(e)}")
            return {}

    def _load_account_blacklist_patterns(self):
        """
        Loads blacklist_patterns from config/accounts.yaml if present.
        """
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            accounts_path = os.path.join(base_dir, 'config', 'accounts.yaml')
            if not os.path.exists(accounts_path):
                return []
            with open(accounts_path, 'r') as file:
                data = yaml.safe_load(file)
                return data.get('blacklist_patterns', [])
        except Exception as e:
            self.logger.error(f"Error loading account blacklist_patterns: {str(e)}")
            return []

    def score_email_for_recruiter(self, email_message):
        score = 0
        from_email = self._get_sender_email(email_message)
        domain = from_email.split('@')[-1].lower() if '@' in from_email else ''
        subject = self._get_email_subject(email_message)
        sender_name = parseaddr(email_message.get('From', ''))[0]
        body = self._get_email_body(email_message)

        # Combine blacklist patterns from rules.yaml and accounts.yaml
        blacklist_patterns = set(self.rules.get('blacklist_patterns', []))
        if self.account_blacklist_patterns:
            blacklist_patterns.update(self.account_blacklist_patterns)

        # Strongly penalize/skip job board/marketing/system senders
        if self._is_job_board_or_marketing(from_email, domain):
            self.logger.info(f"Skipping job board/marketing sender: {from_email}")
            return -100  # Skip completely
        if self._is_system_or_generic_sender(from_email):
            self.logger.info(f"Skipping system/generic sender: {from_email}")
            return -100  # Skip completely

        # Penalize or skip if sender domain or email matches any blacklist pattern
        if any(re.fullmatch(pattern, domain) for pattern in blacklist_patterns):
            self.logger.info(f"Sender domain blacklisted: {domain}")
            return -100  # Skip completely

        if any(re.fullmatch(pattern, from_email) for pattern in blacklist_patterns):
            self.logger.info(f"Sender email blacklisted: {from_email}")
            return -100  # Skip completely

        # 1. Domain not in blacklist (already checked above, so just reward if not blacklisted)
        score += 1

        # 2. Recruiter keywords in subject or sender name
        recruiter_keywords = self.rules.get('recruiter_keywords', [])
        if any(kw.lower() in subject.lower() for kw in recruiter_keywords) or \
           any(kw.lower() in sender_name.lower() for kw in recruiter_keywords):
            score += 1

        # 3. Recruiter title in signature
        recruiter_titles = self.rules.get('signature_patterns', {}).get('recruiter_title', [])
        if any(re.search(pattern, body, re.IGNORECASE) for pattern in recruiter_titles):
            score += 2

        # 4. LinkedIn/company URL in signature
        linkedin_patterns = self.rules.get('signature_patterns', {}).get('linkedin', [])
        if any(re.search(pattern, body, re.IGNORECASE) for pattern in linkedin_patterns):
            score += 1

        # 5. Exclusion patterns in sender email (already handled above with blacklist)
        # (No further penalty here)

        return score

    def is_recruiter_email(self, email_message):
        score = self.score_email_for_recruiter(email_message)
        self.logger.info(f"Recruiter score for email: {score}")
        return score >= 2

    def _validate_domain(self, domain):
        if not domain:
            return False

        strategy = self.rules.get('domain_strategy', 'hybrid')

        # Combine blacklist patterns from rules.yaml and accounts.yaml
        blacklist_patterns = set(self.rules.get('blacklist_patterns', []))
        if self.account_blacklist_patterns:
            blacklist_patterns.update(self.account_blacklist_patterns)

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
                for pattern in blacklist_patterns
            )
        else:  # hybrid - must be in whitelist AND not in blacklist
            whitelisted = any(
                re.fullmatch(pattern, domain)
                for pattern in self.rules.get('whitelist_domains', [])
            )
            blacklisted = any(
                re.fullmatch(pattern, domain)
                for pattern in blacklist_patterns
            )
            return whitelisted and not blacklisted

    # --- REFINED FIELD EXTRACTION METHODS ---

    def _extract_real_name(self, sender_name, sender_email, body):
        """
        Extracts and validates the real name.
        Priority: sender display name > signature parsing.
        """
        def clean_name(name):
            if not name:
                return None
            name = name.strip()
            # Remove quotes, extra whitespace, and email addresses
            name = re.sub(r'["\'<>]', '', name)
            name = re.sub(r'\s+', ' ', name)
            # Remove if it looks like an email
            if re.match(r'^[\w\.-]+@[\w\.-]+$', name):
                return None
            # Remove generic/system names
            generic_words = set(word.lower() for word in self.rules.get('generic_company_words', []))
            if name.lower() in generic_words or len(name) < 2:
                return None
            # Remove if all uppercase or all lowercase (likely not a real name)
            if name.isupper() or name.islower():
                return None
            # Remove if only one word
            if len(name.split()) < 2:
                return None
            # Remove if contains numbers
            if re.search(r'\d', name):
                return None
            return name

        # 1. Try sender display name
        cleaned = clean_name(sender_name)
        if cleaned:
            return cleaned

        # 2. Try signature patterns in body
        signature_patterns = [
            r'(?i)(?:Best|Regards|Thanks|Thank you|Sincerely|Cheers|Kind regards|Warm regards|Respectfully|Yours truly|Cordially|With appreciation)[,\s\n]+([A-Z][a-z]+(?: [A-Z][a-z]+)+)',
            r'(?i)^([A-Z][a-z]+(?: [A-Z][a-z]+)+)[\s\n]*[\-,]?$'  # Standalone name at end
        ]
        for pattern in signature_patterns:
            match = re.search(pattern, body)
            if match:
                sig_name = clean_name(match.group(1))
                if sig_name:
                    return sig_name
        return None

    def _extract_company(self, sender_email, body):
        """
        Extracts and validates the company.
        Priority: sender domain > signature parsing.
        """
        generic_words = set(word.lower() for word in self.rules.get('generic_company_words', []))

        # 1. Try from sender domain
        if sender_email and '@' in sender_email:
            domain = sender_email.split('@')[1]
            # Remove common TLDs and subdomains
            domain_parts = domain.split('.')
            if len(domain_parts) > 2:
                company = domain_parts[-3]
            else:
                company = domain_parts[0]
            company = company.replace('-', ' ').replace('_', ' ').capitalize()
            if company.lower() not in generic_words and len(company) > 2 and not company.isdigit():
                return company

        # 2. Try signature patterns in body
        company_patterns = [
            r'(?i)Company[:\s]+([A-Z][a-zA-Z0-9&\s]+)',
            r'at\s+([A-Z][a-zA-Z\s&]+)',
            r'([A-Z][a-zA-Z\s&]+)\s*Inc',
            r'([A-Z][a-zA-Z\s&]+)\s*LLC',
            r'(?i)\n([A-Z][a-zA-Z0-9&\s]+)\n'  # Standalone line
        ]
        for pattern in company_patterns:
            match = re.search(pattern, body)
            if match:
                company = match.group(1).strip()
                if company.lower() not in generic_words and len(company) > 2 and not company.isdigit():
                    return company
        return None

    def _extract_real_email(self, sender_email, body):
        """
        Extracts and validates the real email.
        Priority: sender email > signature parsing.
        """
        def is_valid_email(email):
            if not email:
                return False
            email = email.strip().lower()
            # Basic email pattern
            if not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
                return False
            # Exclude system/generic
            if self._is_system_or_generic_sender(email):
                return False
            return True

        # 1. Try sender email
        if is_valid_email(sender_email):
            return sender_email.strip().lower()

        # 2. Try to find in body/signature
        email_pattern = r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)'
        matches = re.findall(email_pattern, body)
        for email in matches:
            if is_valid_email(email):
                return email.strip().lower()
        return None

    def _extract_phone(self, body):
        """
        Extracts and validates a phone number from the body.
        """
        phone_patterns = [
            r'\+?[0-9]{1,3}[-.\s]?[0-9]{3,5}[-.\s]?[0-9]{3,5}[-.\s]?[0-9]{3,5}',
            r'\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}'
        ]
        for pattern in phone_patterns:
            for match in re.finditer(pattern, body):
                phone = match.group(0)
                digits = re.sub(r'\D', '', phone)
                # Validate length and not all same digit
                if 10 <= len(digits) <= 15 and not re.match(r'^(\d)\1+$', digits):
                    # Clean up phone: remove extra spaces, keep + if present
                    phone_clean = re.sub(r'[^\d+]', '', phone)
                    return phone_clean
        return None

    def _extract_website(self, sender_email, body):
        """
        Extracts and validates a website URL.
        Priority: sender domain > signature parsing.
        """
        # 1. Try from sender domain
        if sender_email and '@' in sender_email:
            domain = sender_email.split('@')[1]
            # Remove common TLDs and subdomains
            domain = domain.lower()
            if not any(x in domain for x in ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'icloud.com']):
                url = f"https://{domain}"
                # Validate as a URL
                try:
                    parsed = urlparse(url)
                    if parsed.scheme and parsed.netloc:
                        return url
                except Exception:
                    pass

        # 2. Try to find in body
        url_pattern = r'https?://[\w\.-]+(?:/[^\s,;\)>"]*)?'
        matches = re.findall(url_pattern, body)
        for url in matches:
            # Exclude social media
            if not any(social in url for social in ['linkedin.com', 'facebook.com', 'twitter.com']):
                # Validate as a URL
                try:
                    parsed = urlparse(url)
                    if parsed.scheme and parsed.netloc:
                        return url
                except Exception:
                    continue
        return None

    def _extract_linkedin(self, body):
        """
        Extracts and validates a LinkedIn URL from the body.
        """
        linkedin_patterns = self.rules.get('signature_patterns', {}).get('linkedin', [])
        for pattern in linkedin_patterns:
            match = re.search(pattern, body)
            if match:
                url = match.group(0)
                if 'linkedin.com' in url:
                    return url
        # Fallback: find any linkedin.com URL
        url_pattern = r'https?://[\w\.]*linkedin\.com/[^\s,;\)>"]*'
        match = re.search(url_pattern, body)
        if match:
            url = match.group(0)
            # Validate as a URL
            try:
                parsed = urlparse(url)
                if parsed.scheme and parsed.netloc and 'linkedin.com' in parsed.netloc:
                    return url
            except Exception:
                pass
        return None

    def extract_contacts(self, email_message):
        from_header = email_message.get('From', '')
        sender_name, sender_email = parseaddr(from_header)
        body = self._get_email_body(email_message)

        # Name: Prefer sender display name, fallback to signature
        name = self._extract_real_name(sender_name, sender_email, body)

        # Email: Prefer sender email, fallback to signature
        email = self._extract_real_email(sender_email, body)

        # Company: Prefer sender domain, fallback to signature
        company = self._extract_company(sender_email, body)

        # Phone: Use improved phone regexes and validation
        phone = self._extract_phone(body)

        # LinkedIn: Extract and validate
        linkedin_url = self._extract_linkedin(body)

        # Website: Prefer sender domain, fallback to signature
        website = self._extract_website(sender_email, body)

        return {
            'name': name or None,
            'email': email.lower() if email else None,
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

    def _is_job_board_or_marketing(self, email, domain):
        # Implement job board/marketing detection logic
        return False

    def _is_system_or_generic_sender(self, email):
        # Implement system/generic sender detection logic
        return False
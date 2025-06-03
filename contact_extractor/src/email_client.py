import imaplib
import email
from email.header import decode_header
import logging

class EmailClient:
    def __init__(self, email_account):
        self.email = email_account['email']
        self.password = email_account['password']
        self.server = email_account['imap_server']
        self.port = email_account['imap_port']
        self.mail = None
        self.logger = logging.getLogger(__name__)

    def connect(self):
        try:
            self.mail = imaplib.IMAP4_SSL(self.server, self.port)
            self.mail.login(self.email, self.password)
            self.mail.select('inbox')
            status, messages = self.mail.select('inbox')
            print(f"Total emails in inbox: {messages[0].decode()}")
            return True
        except Exception as e:
            self.logger.error(f"Connection failed for {self.email}: {str(e)}")
            return False

    def disconnect(self):
        try:
            if self.mail:
                self.mail.close()
                self.mail.logout()
        except Exception as e:
            self.logger.error(f"Error disconnecting {self.email}: {str(e)}")

    def fetch_emails(self, since_date=None, since_uid=None, batch_size=150):
        if not self.mail:
            if not self.connect():
                return []

        try:
            # Search criteria
            criteria = "ALL"
            if since_date:
                criteria = f'(SINCE "{since_date}")'
            elif since_uid:
                # Only fetch emails with UID > last_uid
                criteria = f'(UID {int(since_uid) + 1}:*)'

            status, messages = self.mail.search(None, criteria)
            if status != 'OK':
                return []

            email_ids = messages[0].split()
            # Sort UIDs in ascending order (oldest to newest)
            email_ids = sorted(email_ids, key=lambda x: int(x))
            # Take the first batch_size emails (oldest first)
            batch_email_ids = email_ids[:batch_size]
            emails = []
            for email_id in batch_email_ids:
                status, msg_data = self.mail.fetch(email_id, '(RFC822)')
                if status != 'OK':
                    continue
                raw_email = msg_data[0][1]
                email_message = email.message_from_bytes(raw_email)
                emails.append({
                    'uid': email_id.decode() if isinstance(email_id, bytes) else str(email_id),
                    'message': email_message,
                    'raw': raw_email
                })

            return emails
        except Exception as e:
            self.logger.error(f"Error fetching emails for {self.email}: {str(e)}")
            return []

    @staticmethod
    def clean_text(text):
        if text is None:
            return ""
        try:
            decoded_text = decode_header(text)[0][0]
            if isinstance(decoded_text, bytes):
                return decoded_text.decode('utf-8', errors='ignore')
            return str(decoded_text)
        except:
            return str(text)
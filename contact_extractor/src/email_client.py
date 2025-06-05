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

    def fetch_emails(self, since_date=None, since_uid=None, batch_size=100, start_index=0):
        """
        Fetch emails in batches for efficiency.
        Returns a tuple: (emails, next_start_index)
        """
        if not self.mail:
            if not self.connect():
                return [], None

        try:
            # Search criteria
            # Update: fetch after last UID, not including it again
            if since_uid:
                # since_uid may be str, ensure int
                try:
                    next_uid = int(since_uid) + 1
                except Exception:
                    next_uid = since_uid  # fallback, but should be int
                criteria = f'(UID {next_uid}:*)'
            else:
                criteria = "ALL"

            # status, messages = self.mail.search(None, criteria)
            status, messages = self.mail.uid('search', None, criteria)

            if status != 'OK':
                return [], None

            email_ids = messages[0].split()
            total_emails = len(email_ids)
            if total_emails == 0 or start_index >= total_emails:
                return [], None

            # Batch slicing
            end_index = min(start_index + batch_size, total_emails)
            batch_ids = email_ids[-end_index: -start_index] if start_index > 0 else email_ids[-end_index:]
            batch_ids = list(reversed(batch_ids))  # newest first

            emails = []
            for email_id in batch_ids:
                # 
                status, msg_data = self.mail.uid('fetch', email_id, '(RFC822)')

                if status != 'OK':
                    continue
                raw_email = msg_data[0][1]
                email_message = email.message_from_bytes(raw_email)
                emails.append({
                    'uid': email_id.decode() if isinstance(email_id, bytes) else str(email_id),
                    'message': email_message,
                    'raw': raw_email
                })

            next_start_index = end_index if end_index < total_emails else None
            return emails, next_start_index
        except Exception as e:
            self.logger.error(f"Error fetching emails for {self.email}: {str(e)}")
            return [], None

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
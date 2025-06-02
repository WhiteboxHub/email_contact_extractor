import re
import logging
from typing import List, Dict, Any

from extractor import ContactExtractor

class EmailFilter:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def filter_recruiter_emails(self, emails: List[Dict[str, Any]], extractor: ContactExtractor) -> List[Dict[str, Any]]:
        """Filter emails to only include recruiter/vendor emails"""
        recruiter_emails = []
        for email_data in emails:
            try:
                if extractor.is_recruiter_email(email_data['message']):
                    recruiter_emails.append(email_data)
            except Exception as e:
                self.logger.error(f"Error filtering email: {str(e)}")
                continue
        return recruiter_emails
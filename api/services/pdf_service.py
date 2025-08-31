"""
PDF Service for parsing Verizon bills
This service integrates with the existing parse_verizon.py functionality
"""

import os
import tempfile
from typing import Dict, Tuple, List
import parse_verizon
from werkzeug.utils import secure_filename

class PDFService:
    """Service class for handling PDF parsing operations"""
    
    def __init__(self, user_id: int = None):
        self.user_id = user_id
    
    def parse_verizon_bill(self, pdf_file, user_config: Dict = None) -> Dict:
        """
        Parse a Verizon bill PDF using the existing parse_verizon logic
        
        Args:
            pdf_file: Uploaded PDF file
            user_config: User-specific configuration (line mappings, etc.)
            
        Returns:
            Dict containing parsed bill information
        """
        try:
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                pdf_file.save(temp_file.name)
                temp_path = temp_file.name
            
            try:
                # Extract charges using enhanced parse_verizon logic
                account_wide_value, line_details = parse_verizon.extract_charges_from_pdf(temp_path)
                
                # Group by person (this could be customized based on user_config)
                person_totals = parse_verizon.group_by_person(line_details)
                
                # Apply smartwatch discount if applicable
                parse_verizon.adjust_for_smartwatch_discount(person_totals)
                
                # Calculate total
                total_cost = sum(person_totals.values())
                
                # Clean up temporary file
                os.unlink(temp_path)
                
                return {
                    'success': True,
                    'line_details': line_details,
                    'person_totals': person_totals,
                    'account_wide_value': account_wide_value,
                    'total_cost': total_cost,
                    'message': 'PDF parsed successfully'
                }
                
            except Exception as e:
                # Clean up temporary file on error
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise e
                
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to parse PDF: {str(e)}'
            }
    
    def get_bill_breakdown(self, pdf_path: str) -> Dict:
        """
        Get bill breakdown from a PDF file path
        This is a simpler method for when you already have the PDF file path
        """
        try:
            account_wide_value, line_details = parse_verizon.extract_charges_from_pdf(pdf_path)
            person_totals = parse_verizon.group_by_person(line_details)
            parse_verizon.adjust_for_smartwatch_discount(person_totals)
            
            total_cost = sum(person_totals.values())
            
            return {
                'success': True,
                'line_details': line_details,
                'person_totals': person_totals,
                'account_wide_value': account_wide_value,
                'total_cost': total_cost
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to get bill breakdown: {str(e)}'
            }
    
    def send_bill_email(self, person_totals: Dict, email_list: List[str] = None, sender_email: str = None) -> Dict:
        """
        Send bill email using the existing parse_verizon email functionality
        
        Args:
            person_totals: Dictionary of person totals (can be family totals)
            email_list: List of email addresses to send to
            
        Returns:
            Dict containing email send status
        """
        try:
            # Use default email list if none provided
            if email_list is None:
                email_list = parse_verizon.email_list
            
            # Call the existing send_email function
            parse_verizon.send_email(person_totals, email_list, sender_email)
            
            return {
                'success': True,
                'message': 'Bill email sent successfully',
                'emails_sent': len(email_list)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to send email: {str(e)}'
            }
    


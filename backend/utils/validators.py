import re
import logging

logger = logging.getLogger(__name__)

def validate_email(email: str) -> bool:
    """
    Validate email format.
    Returns True if valid, False otherwise.
    """
    try:
        if not email or not isinstance(email, str):
            return False
        
        # Basic email format validation
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    except Exception as e:
        logger.error(f"Error validating email: {str(e)}", exc_info=True)
        return False

def validate_password(password: str) -> tuple[bool, str]:
    """
    Validate password strength.
    Returns a tuple of (is_valid: bool, error_message: str)
    """
    try:
        if not password or not isinstance(password, str):
            return False, "Password cannot be empty"

        if len(password) < 8:
            return False, "Password must be at least 8 characters long"

        if not re.search(r'[A-Z]', password):
            return False, "Password must contain at least one uppercase letter"

        if not re.search(r'[a-z]', password):
            return False, "Password must contain at least one lowercase letter"

        if not re.search(r'\d', password):
            return False, "Password must contain at least one number"

        return True, ""
    except Exception as e:
        logger.error(f"Error validating password: {str(e)}", exc_info=True)
        return False, "Error validating password"

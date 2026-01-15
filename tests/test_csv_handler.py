import pytest
from app.csv_handler import CSVHandler, CSVValidationError


class TestCSVHandler:
    """Test CSV parsing and validation"""

    def test_valid_csv(self):
        """Test parsing a valid CSV"""
        csv_content = b"""username,email,role,display_name
admin,admin@example.com,admin,Administrator
user1,user1@example.com,user,User One
user2,user2@example.com,user,User Two"""

        users, warnings = CSVHandler.parse_and_validate(csv_content)

        assert len(users) == 3
        assert users[0]["username"] == "admin"
        assert users[0]["email"] == "admin@example.com"
        assert users[0]["role"] == "admin"
        assert users[0]["display_name"] == "Administrator"
        assert len(warnings) == 0

    def test_minimal_csv(self):
        """Test CSV with only required columns"""
        csv_content = b"""username,email
user1,user1@example.com
user2,user2@example.com"""

        users, warnings = CSVHandler.parse_and_validate(csv_content)

        assert len(users) == 2
        assert users[0]["username"] == "user1"
        assert users[0]["email"] == "user1@example.com"
        assert users[0]["role"] == "user"  # Default role
        assert users[0]["display_name"] is None

    def test_missing_required_column(self):
        """Test CSV missing required column"""
        csv_content = b"""username,role
user1,admin"""

        with pytest.raises(CSVValidationError, match="Missing required columns"):
            CSVHandler.parse_and_validate(csv_content)

    def test_empty_csv(self):
        """Test empty CSV file"""
        csv_content = b""

        with pytest.raises(CSVValidationError, match="empty"):
            CSVHandler.parse_and_validate(csv_content)

    def test_duplicate_username(self):
        """Test CSV with duplicate username"""
        csv_content = b"""username,email
user1,user1@example.com
user1,user2@example.com"""

        with pytest.raises(CSVValidationError, match="Duplicate username"):
            CSVHandler.parse_and_validate(csv_content)

    def test_duplicate_email(self):
        """Test CSV with duplicate email"""
        csv_content = b"""username,email
user1,user@example.com
user2,user@example.com"""

        with pytest.raises(CSVValidationError, match="Duplicate email"):
            CSVHandler.parse_and_validate(csv_content)

    def test_invalid_email(self):
        """Test CSV with invalid email"""
        csv_content = b"""username,email
user1,not-an-email"""

        with pytest.raises(CSVValidationError, match="email"):
            CSVHandler.parse_and_validate(csv_content)

    def test_empty_username(self):
        """Test CSV with empty username"""
        csv_content = b"""username,email
,user@example.com"""

        with pytest.raises(CSVValidationError, match="username cannot be empty"):
            CSVHandler.parse_and_validate(csv_content)

    def test_email_normalization(self):
        """Test that emails are normalized to lowercase"""
        csv_content = b"""username,email
user1,User@Example.COM"""

        users, warnings = CSVHandler.parse_and_validate(csv_content)

        assert users[0]["email"] == "user@example.com"

    def test_whitespace_handling(self):
        """Test that whitespace is stripped"""
        csv_content = b"""username,email
  user1  ,  user@example.com  """

        users, warnings = CSVHandler.parse_and_validate(csv_content)

        assert users[0]["username"] == "user1"
        assert users[0]["email"] == "user@example.com"

    def test_unknown_columns_warning(self):
        """Test that unknown columns generate warnings"""
        csv_content = b"""username,email,unknown_col
user1,user@example.com,value"""

        users, warnings = CSVHandler.parse_and_validate(csv_content)

        assert len(users) == 1
        assert len(warnings) > 0
        assert "unknown" in warnings[0].lower()

    def test_empty_rows_skipped(self):
        """Test that empty rows are skipped with warning"""
        csv_content = b"""username,email
user1,user1@example.com

user2,user2@example.com"""

        users, warnings = CSVHandler.parse_and_validate(csv_content)

        assert len(users) == 2
        assert any("empty row" in w.lower() for w in warnings)

    def test_to_csv_string(self):
        """Test converting users back to CSV string"""
        users = [
            {"username": "user1", "email": "user1@example.com", "role": "admin", "display_name": "User One"},
            {"username": "user2", "email": "user2@example.com", "role": "user", "display_name": None}
        ]

        csv_string = CSVHandler.to_csv_string(users)

        assert "username,email,role,display_name" in csv_string
        assert "user1,user1@example.com,admin,User One" in csv_string
        assert "user2" in csv_string

    def test_file_size_validation(self):
        """Test file size validation"""
        # Should pass
        CSVHandler.validate_file_size(1024 * 1024)  # 1MB

        # Should fail
        with pytest.raises(CSVValidationError, match="exceeds maximum"):
            CSVHandler.validate_file_size(10 * 1024 * 1024)  # 10MB (default max is 5MB)

    def test_non_utf8_encoding(self):
        """Test that non-UTF8 files are rejected"""
        csv_content = b"\xff\xfe"  # Invalid UTF-8

        with pytest.raises(CSVValidationError, match="UTF-8"):
            CSVHandler.parse_and_validate(csv_content)

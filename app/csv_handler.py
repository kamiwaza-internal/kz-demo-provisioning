import csv
import io
from typing import List, Dict, Tuple
from app.schemas import UserRow
from pydantic import ValidationError


class CSVValidationError(Exception):
    """Custom exception for CSV validation errors"""
    pass


class CSVHandler:
    REQUIRED_COLUMNS = {"email"}
    OPTIONAL_COLUMNS = set()
    ALL_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS

    @staticmethod
    def parse_and_validate(file_content: bytes) -> Tuple[List[Dict], List[str]]:
        """
        Parse and validate CSV file content.

        Returns:
            Tuple of (parsed_rows, warnings)

        Raises:
            CSVValidationError: If CSV is invalid
        """
        warnings = []

        try:
            content_str = file_content.decode('utf-8')
        except UnicodeDecodeError:
            raise CSVValidationError("File must be UTF-8 encoded")

        # Parse CSV
        reader = csv.DictReader(io.StringIO(content_str))

        if not reader.fieldnames:
            raise CSVValidationError("CSV file is empty or has no headers")

        # Validate headers
        headers = set(reader.fieldnames)
        missing_required = CSVHandler.REQUIRED_COLUMNS - headers
        if missing_required:
            raise CSVValidationError(f"Missing required columns: {', '.join(missing_required)}")

        unknown_columns = headers - CSVHandler.ALL_COLUMNS
        if unknown_columns:
            warnings.append(f"Unknown columns will be ignored: {', '.join(unknown_columns)}")

        # Parse and validate rows
        parsed_rows = []
        seen_emails = set()
        row_num = 1

        for row_dict in reader:
            row_num += 1

            # Skip empty rows
            if not any(row_dict.values()):
                warnings.append(f"Row {row_num}: Empty row skipped")
                continue

            try:
                # Extract only known columns
                filtered_row = {k: v for k, v in row_dict.items() if k in CSVHandler.ALL_COLUMNS}

                # Normalize data
                filtered_row["email"] = filtered_row.get("email", "").strip().lower()

                if not filtered_row["email"]:
                    raise ValueError("email cannot be empty")

                # Validate with Pydantic
                user = UserRow(**filtered_row)
                user_dict = user.model_dump()

                # Check for duplicates
                if user_dict["email"] in seen_emails:
                    raise ValueError(f"Duplicate email: {user_dict['email']}")

                seen_emails.add(user_dict["email"])
                parsed_rows.append(user_dict)

            except ValidationError as e:
                errors = "; ".join([f"{err['loc'][0]}: {err['msg']}" for err in e.errors()])
                raise CSVValidationError(f"Row {row_num}: {errors}")
            except ValueError as e:
                raise CSVValidationError(f"Row {row_num}: {str(e)}")

        if not parsed_rows:
            raise CSVValidationError("No valid user rows found in CSV")

        return parsed_rows, warnings

    @staticmethod
    def to_csv_string(users: List[Dict]) -> str:
        """Convert list of user dicts back to CSV string"""
        if not users:
            return ""

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["email"])
        writer.writeheader()
        writer.writerows(users)
        return output.getvalue()

    @staticmethod
    def validate_file_size(file_size: int, max_size_mb: int = 5) -> None:
        """Validate file size"""
        max_bytes = max_size_mb * 1024 * 1024
        if file_size > max_bytes:
            raise CSVValidationError(f"File size exceeds maximum of {max_size_mb}MB")

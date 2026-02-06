import csv
import json
import io
from typing import List, Dict, Any
from collections import Counter
from datetime import datetime


class LogAnalyzer:
    """
    Analyzer for log files containing structured JSON logs from StructuredLoggingMiddleware.
    
    Supported formats:
    1. CSV format:
       - First row: headers (at minimum should have a column with JSON log entries)
       - Subsequent rows: log entries in JSON format
    
    2. Newline-delimited JSON (.log files):
       - Each line contains a complete JSON object
       - No headers required
    """
    
    def __init__(self, log_content: bytes, file_format: str = 'csv'):
        """
        Initialize with log content.
        
        Args:
            log_content: Raw bytes of the log file
            file_format: Format of the log file ('csv' or 'ndjson')
        """
        self.log_content = log_content
        self.file_format = file_format
        self.logs: List[Dict[str, Any]] = []
        self.parse_errors: List[str] = []
    
    def parse(self) -> None:
        """
        Parse the log file and extract structured log entries.
        
        For CSV files:
        - The CSV may have various formats:
          1. Single column with JSON strings
          2. Multiple columns where one contains the JSON log entry
          3. Columns that represent the flattened log structure
        
        For NDJSON files (.log):
        - Each line contains a complete JSON object
        """
        if self.file_format == 'ndjson':
            self._parse_ndjson()
        else:
            self._parse_csv()
    
    def _parse_ndjson(self) -> None:
        """
        Parse newline-delimited JSON log file.
        Each line should be a complete JSON object.
        """
        try:
            content = self.log_content.decode('utf-8')
        except UnicodeDecodeError:
            # Try alternative encoding
            content = self.log_content.decode('utf-8-sig', errors='replace')
        
        lines = content.strip().split('\n')
        
        for line_num, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:  # Skip empty lines
                continue
            
            try:
                log_entry = json.loads(line)
                self.logs.append(log_entry)
            except json.JSONDecodeError as e:
                self.parse_errors.append(f"Line {line_num}: Invalid JSON - {str(e)}")
            except Exception as e:
                self.parse_errors.append(f"Line {line_num}: {str(e)}")
    
    def _parse_csv(self) -> None:
        """
        Parse CSV log file.
        """
        try:
            content = self.log_content.decode('utf-8')
        except UnicodeDecodeError:
            # Try alternative encoding
            content = self.log_content.decode('utf-8-sig', errors='replace')
        
        csv_file = io.StringIO(content)
        
        # Try to detect CSV dialect automatically to handle different delimiters
        try:
            sample = content[:8192]  # Use first 8KB for dialect detection
            # Provide delimiters hint to avoid detecting spaces as delimiters
            dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
            csv_file.seek(0)
            reader = csv.DictReader(csv_file, dialect=dialect)
        except (csv.Error, Exception):
            # Fall back to default dialect if detection fails
            csv_file.seek(0)
            reader = csv.DictReader(csv_file)
        
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
            try:
                # Skip completely empty rows
                if not row or not any(v for v in row.values() if v):
                    continue
                
                # Try to find JSON in the row
                log_entry = self._extract_log_entry(row)
                if log_entry:
                    self.logs.append(log_entry)
            except Exception as e:
                self.parse_errors.append(f"Row {row_num}: {str(e)}")
    
    def _extract_log_entry(self, row: Dict[str, str]) -> Dict[str, Any]:
        """
        Extract log entry from a CSV row.
        
        Tries multiple strategies:
        1. Look for a column with JSON content
        2. If the row itself looks like a structured log, use it directly
        """
        # Strategy 1: Look for columns that contain JSON
        for key, value in row.items():
            # Add null/None check and type validation
            if value and isinstance(value, str):
                value = value.strip()
                if value.startswith('{') and value.endswith('}'):
                    try:
                        return json.loads(value)
                    except json.JSONDecodeError:
                        continue
        
        # Strategy 2: Check if the row has 'message' field (structured log format)
        if 'message' in row and row.get('message'):
            # Reconstruct the log entry from CSV columns
            log_entry = {
                'message': row.get('message', ''),
                'timestamp': row.get('timestamp', ''),
            }
            
            # Add attributes if present
            if 'level' in row or 'attributes.level' in row:
                log_entry['attributes'] = {
                    'level': row.get('level') or row.get('attributes.level', 'info')
                }
            
            # Add tags if present
            tags = {}
            for key, value in row.items():
                if key.startswith('tags.') and value:
                    tag_name = key.replace('tags.', '')
                    tags[tag_name] = value
            if tags:
                log_entry['tags'] = tags
            
            return log_entry
        
        # Strategy 3: If there's only one column, try to parse it as JSON
        if len(row) == 1:
            value = list(row.values())[0]
            if value and isinstance(value, str):
                value = value.strip()
                if value.startswith('{') and value.endswith('}'):
                    try:
                        return json.loads(value)
                    except json.JSONDecodeError:
                        pass
        
        return None
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Calculate statistics from the parsed logs.
        
        Returns:
            Dictionary with statistics including:
            - total_requests: Total number of HTTP requests logged
            - status_codes: Distribution of HTTP status codes
            - methods: Distribution of HTTP methods
            - paths: Distribution of request paths
            - error_rate: Percentage of 4xx and 5xx responses
            - time_range: Earliest and latest timestamps
        """
        if not self.logs:
            return {
                "total_requests": 0,
                "error": "No valid log entries found",
                "parse_errors": self.parse_errors
            }
        
        stats = {
            "total_requests": len(self.logs),
            "status_codes": {},
            "methods": {},
            "paths": {},
            "error_rate": 0.0,
            "time_range": {},
            "parse_errors_count": len(self.parse_errors)
        }
        
        status_codes = []
        methods = []
        paths = []
        timestamps = []
        errors = 0
        
        for log in self.logs:
            message = log.get('message', '')
            
            # Extract HTTP status code from message
            # Format: "IP:PORT - "METHOD PATH HTTP/VERSION" STATUS PHRASE"
            if ' - "' in message and '"' in message[message.index(' - "')+4:]:
                try:
                    parts = message.split('"')
                    if len(parts) >= 3:
                        # Extract request parts: "METHOD PATH HTTP/VERSION"
                        request_parts = parts[1].split()
                        if len(request_parts) >= 2:
                            method = request_parts[0]
                            path = request_parts[1]
                            methods.append(method)
                            paths.append(path)
                        
                        # Extract status code from the part after the closing quote
                        after_request = parts[2].strip()
                        status_parts = after_request.split()
                        if status_parts:
                            status_code = status_parts[0]
                            status_codes.append(status_code)
                            
                            # Count errors (4xx and 5xx)
                            if status_code.startswith('4') or status_code.startswith('5'):
                                errors += 1
                except Exception:
                    pass
            
            # Extract timestamp
            timestamp = log.get('timestamp')
            if timestamp:
                timestamps.append(timestamp)
        
        # Calculate distributions
        stats['status_codes'] = dict(Counter(status_codes))
        stats['methods'] = dict(Counter(methods))
        stats['paths'] = dict(Counter(paths))
        
        # Calculate error rate
        if len(status_codes) > 0:
            stats['error_rate'] = round((errors / len(status_codes)) * 100, 2)
        
        # Calculate time range
        if timestamps:
            stats['time_range'] = {
                'earliest': min(timestamps),
                'latest': max(timestamps)
            }
        
        return stats

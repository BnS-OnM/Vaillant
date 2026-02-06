import csv
import json
import io
from typing import List, Dict, Any
from collections import Counter
from datetime import datetime


class LogAnalyzer:
    """
    Analyzer for CSV log files containing structured JSON logs from StructuredLoggingMiddleware.
    
    Expected CSV format:
    - First row: headers (at minimum should have a column with JSON log entries)
    - Subsequent rows: log entries in JSON format
    """
    
    def __init__(self, csv_content: bytes):
        """Initialize with CSV content."""
        self.csv_content = csv_content
        self.logs: List[Dict[str, Any]] = []
        self.parse_errors: List[str] = []
    
    def parse(self) -> None:
        """
        Parse the CSV file and extract structured log entries.
        
        The CSV may have various formats:
        1. Single column with JSON strings
        2. Multiple columns where one contains the JSON log entry
        3. Columns that represent the flattened log structure
        """
        try:
            content = self.csv_content.decode('utf-8')
        except UnicodeDecodeError:
            # Try alternative encoding
            content = self.csv_content.decode('utf-8-sig', errors='replace')
        
        csv_file = io.StringIO(content)
        reader = csv.DictReader(csv_file)
        
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
            try:
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
            if value and value.strip().startswith('{'):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    continue
        
        # Strategy 2: Check if the row has 'message' field (structured log format)
        if 'message' in row:
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
                if key.startswith('tags.'):
                    tag_name = key.replace('tags.', '')
                    tags[tag_name] = value
            if tags:
                log_entry['tags'] = tags
            
            return log_entry
        
        # Strategy 3: If there's only one column, try to parse it as JSON
        if len(row) == 1:
            value = list(row.values())[0]
            if value and value.strip().startswith('{'):
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

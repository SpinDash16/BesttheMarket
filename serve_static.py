"""Minimal static file server for preview — avoids os.getcwd() issues."""
import http.server
import os
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8082
DIRECTORY = "static"

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)
    def log_message(self, format, *args):
        pass  # suppress logs

with http.server.HTTPServer(("", PORT), Handler) as httpd:
    httpd.serve_forever()

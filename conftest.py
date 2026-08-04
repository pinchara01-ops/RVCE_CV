"""Repository-wide test safeguards.

Several retrieval integration fixtures recreate their target Qdrant
collection. Tests must never default to the interactive video library.
"""
import os


os.environ["COLLECTION_NAME"] = "video_windows_query_test"

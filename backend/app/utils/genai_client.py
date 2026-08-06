"""
Centralized Gemini API client configuration with round-robin key rotation.

Supports multiple API keys for load balancing and quota management.
"""

import os
import threading
import google.generativeai as genai
from dotenv import load_dotenv
from typing import Optional, List


class GenAIClient:
    """
    A thread-safe Gemini API client with round-robin key rotation.
    
    Features:
    - Automatic key rotation across multiple API keys
    - Quota error detection and key skipping
    - Permanent blocking of leaked/invalid keys (403 errors)
    - Thread-safe counter for concurrent access
    - Retry with next key on failure
    """
    
    _configured = False
    _api_keys: List[str] = []
    _current_index = 0
    _lock = threading.Lock()
    _failed_keys: set = set()  # Track temporarily failed keys (quota)
    _permanently_blocked_keys: set = set()  # Track leaked/invalid keys (403)
    
    @classmethod
    def _load_api_keys(cls) -> List[str]:
        """Load API keys from environment, supporting comma-separated list."""
        load_dotenv()
        
        # First try the multi-key format
        keys_str = os.getenv("GEMINI_API_KEYS", "")
        if keys_str:
            keys = [k.strip() for k in keys_str.split(",") if k.strip() and "your_" not in k]
            if keys:
                return keys
        
        # Fallback to single key format
        single_key = os.getenv("GEMINI_API_KEY", "")
        if single_key and "your_" not in single_key:
            return [single_key]
        
        return []
    
    @classmethod
    def configure(cls) -> bool:
        """
        Configure the Gemini API client if not already configured.
        Returns True if at least one valid key is available.
        """
        if not cls._configured:
            cls._api_keys = cls._load_api_keys()
            
            if cls._api_keys:
                # Configure with first key initially
                genai.configure(api_key=cls._api_keys[0])
                cls._configured = True
                print(f"✓ Gemini API configured with {len(cls._api_keys)} keys (round-robin enabled)")
            else:
                print("⚠️ WARNING: No valid GEMINI_API_KEYS configured")
                return False
        
        return cls._configured
    
    @classmethod
    def get_next_key(cls) -> Optional[str]:
        """
        Get the next API key in round-robin fashion.
        Thread-safe implementation. Skips permanently blocked keys.
        """
        if not cls._api_keys:
            return None
        
        with cls._lock:
            # Try to find a non-failed key
            attempts = 0
            while attempts < len(cls._api_keys):
                key = cls._api_keys[cls._current_index]
                cls._current_index = (cls._current_index + 1) % len(cls._api_keys)
                
                # Skip permanently blocked keys (leaked)
                if key in cls._permanently_blocked_keys:
                    attempts += 1
                    continue
                
                if key not in cls._failed_keys:
                    return key
                
                attempts += 1
            
            # All keys failed, clear failed list and try again
            cls._failed_keys.clear()
            key = cls._api_keys[cls._current_index]
            cls._current_index = (cls._current_index + 1) % len(cls._api_keys)
            return key
    
    @classmethod
    def mark_key_failed(cls, api_key: str, permanent: bool = False):
        """
        Mark a key as failed.
        
        Args:
            api_key: The API key that failed
            permanent: If True, permanently block the key (used for 403 leaked keys)
        """
        with cls._lock:
            if permanent:
                cls._permanently_blocked_keys.add(api_key)
                remaining = len(cls._api_keys) - len(cls._permanently_blocked_keys)
                print(f"🔒 API key PERMANENTLY blocked (leaked/invalid). {remaining} keys remaining.")
            else:
                cls._failed_keys.add(api_key)
                remaining = len(cls._api_keys) - len(cls._failed_keys) - len(cls._permanently_blocked_keys)
                print(f"⚠️ API key temporarily failed. {remaining} keys remaining.")
    
    @classmethod
    def clear_failed_keys(cls):
        """Clear all failed key markers (e.g., on new day/quota reset)."""
        with cls._lock:
            cls._failed_keys.clear()
    
    @classmethod
    def get_model(cls, model_name: str = "gemini-2.5-flash"):
        """
        Get a generative model instance with the next available API key.
        
        Returns None if no API keys are configured.
        Uses round-robin rotation for load balancing.
        """
        if not cls.configure():
            print("WARNING: Gemini API not configured - returning None")
            return None
        
        # Get next key and configure
        api_key = cls.get_next_key()
        if not api_key:
            print("WARNING: No available API keys")
            return None
        
        # Reconfigure with the selected key
        genai.configure(api_key=api_key)
        
        return genai.GenerativeModel(model_name)
    
    @classmethod
    def get_key_count(cls) -> int:
        """Get the number of configured API keys."""
        if not cls._api_keys:
            cls._api_keys = cls._load_api_keys()
        return len(cls._api_keys)
    
    @classmethod
    def get_healthy_key_count(cls) -> int:
        """Get the number of non-failed API keys."""
        return len(cls._api_keys) - len(cls._failed_keys)

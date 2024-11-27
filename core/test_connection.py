import os
from openai import AzureOpenAI
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_connection():
    """Test the OpenAI connection"""
    try:
        # Create test client
        client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/"),
            api_version="2024-02-15-preview",
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            timeout=30.0
        )
        
        # Log configuration
        logger.info(f"Testing connection to: {client.base_url}")
        
        # Try a simple completion
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "test"}
            ],
            max_tokens=5,
            temperature=0.3
        )
        
        logger.info("Connection test successful!")
        logger.info(f"Response: {response.choices[0].message.content}")
        return True
        
    except Exception as e:
        logger.error(f"Connection test failed: {str(e)}", exc_info=True)
        return False

if __name__ == "__main__":
    test_connection() 
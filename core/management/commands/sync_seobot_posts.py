import os
from django.core.management.base import BaseCommand
from django.utils.text import slugify
import requests
from core.models import BlogPost
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Syncs blog posts from SEObot'

    def _fetch_index(self, api_key):
        """Fetch and decompress the blog index"""
        url = f'https://cdn.seobotai.com/{api_key}/system/base.json'
        self.stdout.write(f'Fetching index from: {url}')
        
        try:
            response = requests.get(url)
            self.stdout.write(f'Response status code: {response.status_code}')
            
            if response.status_code != 200:
                self.stderr.write(f'Error response from API: {response.text}')
                return []
                
            response.raise_for_status()
            compressed_index = response.json()
            
            if isinstance(compressed_index, bytes):
                compressed_index = compressed_index.decode('utf-8')
            if isinstance(compressed_index, str):
                import json
                compressed_index = json.loads(compressed_index)
            
            self.stdout.write(f'Raw response data: {compressed_index[:2]}')  # Show first 2 items for debugging
            
            # Decompress index entries
            decompressed = []
            for item in compressed_index:
                try:
                    decompressed.append({
                        'id': item.get('id'),
                        'slug': item.get('s'),
                        'headline': item.get('h'),
                        'created_at': item.get('cr'),
                    })
                except Exception as e:
                    self.stderr.write(f'Error decompressing item: {item}, Error: {str(e)}')
                    continue
                    
            self.stdout.write(f'Decompressed {len(decompressed)} articles')
            if decompressed:
                self.stdout.write(f'Sample decompressed article: {decompressed[0]}')
                
            return sorted(decompressed, key=lambda x: x['created_at'], reverse=True)
            
        except requests.exceptions.RequestException as e:
            self.stderr.write(f'Network error fetching index: {str(e)}')
            return []
        except ValueError as e:
            self.stderr.write(f'JSON parsing error: {str(e)}')
            return []
        except Exception as e:
            self.stderr.write(f'Unexpected error in _fetch_index: {str(e)}')
            return []

    def _fetch_article(self, api_key, article_id):
        """Fetch full article content"""
        url = f'https://cdn.seobotai.com/{api_key}/blog/{article_id}.json'
        self.stdout.write(f'Fetching article from: {url}')
        
        try:
            response = requests.get(url)
            self.stdout.write(f'Article response status code: {response.status_code}')
            
            if response.status_code != 200:
                self.stderr.write(f'Error response from API: {response.text}')
                return None
                
            response.raise_for_status()
            article_data = response.json()
            
            # Log the article data structure
            self.stdout.write(f'Article data keys: {article_data.keys()}')
            
            # Return the article data
            return article_data
            
        except Exception as e:
            self.stderr.write(f'Error fetching article {article_id}: {str(e)}')
            return None

    def handle(self, *args, **options):
        api_key = os.getenv('SEOBOT_API_KEY')
        if not api_key:
            self.stderr.write('SEOBOT_API_KEY not found in environment variables')
            return
            
        self.stdout.write(f'Using API key: {api_key[:4]}...{api_key[-4:]}')  # Show first/last 4 chars only

        try:
            # Fetch all articles from index
            self.stdout.write('Starting to fetch index...')
            index = self._fetch_index(api_key)
            self.stdout.write(f'Found {len(index)} articles in index')

            for article in index:
                try:
                    # Fetch full article
                    self.stdout.write(f'\nProcessing article: {article["headline"]} ({article["id"]})')
                    full_article = self._fetch_article(api_key, article['id'])
                    
                    if not full_article:
                        self.stderr.write(f'Skipping article {article["id"]} - could not fetch content')
                        continue
                    
                    # Create or update blog post
                    post, created = BlogPost.objects.get_or_create(
                        slug=article['slug'],
                        defaults={
                            'title': article['headline'],
                            'html_content': full_article.get('html', ''),  # Try html key first
                        }
                    )

                    if not created:
                        post.title = article['headline']
                        post.html_content = full_article.get('html', '')  # Try html key first
                    
                    post.save()
                    
                    action = 'Created' if created else 'Updated'
                    self.stdout.write(f'{action} post: {post.title}')

                except Exception as e:
                    self.stderr.write(f'Error processing article {article.get("id", "unknown")}: {str(e)}')
                    continue

        except Exception as e:
            self.stderr.write(f'Error syncing posts: {str(e)}') 
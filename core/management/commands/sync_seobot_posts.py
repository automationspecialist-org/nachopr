import os
from django.core.management.base import BaseCommand
from django.utils.text import slugify
import requests
from core.models import BlogPost
import logging
from django.conf import settings
import openai
import replicate
from django.core.files.base import ContentFile
import time

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Syncs blog posts from SEObot'

    def _get_shortened_title(self, title):
        """Use OpenAI to generate a 2-4 word shortened title"""
        try:
            client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that shortens titles to 2-4 impactful words."},
                    {"role": "user", "content": f"Shorten this title to 2-4 words, keeping the main topic: {title}"}
                ],
                max_tokens=20,
                temperature=0.7
            )
            shortened_title = response.choices[0].message.content.strip().strip('"')
            self.stdout.write(f'Shortened title: {shortened_title}')
            return shortened_title
        except Exception as e:
            self.stderr.write(f'Error shortening title: {str(e)}')
            return title[:30]  # Fallback to truncated original title

    def _generate_image(self, title):
        """Generate an image using Replicate"""
        try:
            prompt = f"a beautiful typographic poster with a bright green cat, and the text \"{title}\""
            self.stdout.write(f'Starting image generation with prompt: {prompt}')
            
            # Start the generation
            output = replicate.run(
                "ideogram-ai/ideogram-v2",
                input={
                    "prompt": prompt,
                    "resolution": "None",
                    "style_type": "Anime",
                    "aspect_ratio": "16:9",
                    "magic_prompt_option": "Auto"
                }
            )
            
        
            image_url = output
            if image_url:
                self.stdout.write(f'Generated image URL: {image_url}')
                
                # Download the image
                response = requests.get(image_url)
                if response.status_code == 200:
                    self.stdout.write('Successfully downloaded image')
                    return ContentFile(response.content, name=f"{slugify(title)[:50]}.png")
                else:
                    self.stderr.write(f'Failed to download image: {response.status_code}')

            
            return None
        except Exception as e:
            self.stderr.write(f'Error generating image: {str(e)}')
            return None

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
                            'html_content': full_article.get('html', ''),
                        }
                    )

                    if not created:
                        post.title = article['headline']
                        post.html_content = full_article.get('html', '')
                    
                    # Generate image if one doesn't exist
                    if not post.featured_image:
                        self.stdout.write('No featured image found, generating one...')
                        shortened_title = self._get_shortened_title(post.title)
                        image_file = self._generate_image(shortened_title)
                        if image_file:
                            post.featured_image = image_file
                            self.stdout.write('Successfully generated and saved image')
                            post.save()
                        else:
                            self.stderr.write('Failed to generate image')
                    else:
                        self.stdout.write('Post already has a featured image')
                    
                    post.save()
                    
                    action = 'Created' if created else 'Updated'
                    self.stdout.write(f'{action} post: {post.title}')

                except Exception as e:
                    self.stderr.write(f'Error processing article {article.get("id", "unknown")}: {str(e)}')
                    continue

        except Exception as e:
            self.stderr.write(f'Error syncing posts: {str(e)}') 
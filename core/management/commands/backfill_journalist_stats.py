from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import Journalist, NewsPage, DbStat
from django.db import transaction

class Command(BaseCommand):
    help = 'Backfills journalist and news article statistics for the past 30 days'

    def handle(self, *args, **kwargs):
        with transaction.atomic():
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=30)
            
            # Delete all existing stats in our date range
            self.stdout.write('Deleting existing stats...')
            DbStat.objects.filter(
                date__gte=timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time())),
                date__lte=timezone.make_aware(timezone.datetime.combine(end_date, timezone.datetime.max.time()))
            ).delete()
            
            # Create new stats
            for i in range(31):
                current_date = start_date + timedelta(days=i)
                current_datetime = timezone.make_aware(timezone.datetime.combine(current_date, timezone.datetime.min.time()))
                
                # Count journalists created on this day
                journalists_added = Journalist.objects.filter(
                    created_at__date=current_date
                ).count()
                
                # Get total journalists up to this point
                total_journalists = Journalist.objects.filter(
                    created_at__date__lte=current_date
                ).count()
                
                # Count news articles added on this day
                articles_added = NewsPage.objects.filter(
                    crawled_at__date=current_date,
                    is_news_article=True
                ).count()
                
                # Get total news articles up to this point
                total_articles = NewsPage.objects.filter(
                    crawled_at__date__lte=current_date,
                    is_news_article=True
                ).count()
                
                # Create new stat
                DbStat.objects.create(
                    date=current_datetime,
                    num_journalists=total_journalists,
                    num_journalists_added_today=journalists_added,
                    num_news_articles=total_articles,
                    num_news_articles_added_today=articles_added
                )
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Created stats for {current_date}: {journalists_added} journalists, {articles_added} articles added'
                    )
                ) 
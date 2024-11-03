import asyncio

from spider_rs import Website


async def fetch_website(url: str) -> Website:
    website = Website(url)
    website.scrape()
    pages = website.get_pages()
    for page in pages[:1]:
        print(help(page))
        print(page.url)
        print(page.title)
        print(page.content)




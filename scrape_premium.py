#!/usr/bin/env python3
"""
Web Scraper - Premium Interactive CLI
No flags, no complexity - just scrape
"""

import click
import sys
import json
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from smart_scraper import scrape_article, extract_article_for_llm, scrape_with_extraction
from web_scraper import quick_scrape
import re


# Config file for user preferences
CONFIG_FILE = Path.home() / ".scraper_config.json"


def load_config():
    """Load user preferences"""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {
        "default_output_dir": str(Path.home() / "Downloads" / "scraped"),
        "auto_save": True,
        "default_format": "markdown",
        "copy_to_clipboard": False
    }


def save_config(config):
    """Save user preferences"""
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def clean_filename(url):
    """Generate clean filename from URL"""
    parsed = urlparse(url)
    domain = parsed.netloc.replace('www.', '')
    path = parsed.path.strip('/').replace('/', '_')
    
    if path:
        name = f"{domain}_{path}"
    else:
        name = domain
    
    # Clean up
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[-\s]+', '_', name)
    
    # Add timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{name}_{timestamp}"


def auto_save_content(content, url, config, format_type="md"):
    """Automatically save content with smart naming"""
    output_dir = Path(config["default_output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    
    filename = clean_filename(url)
    filepath = output_dir / f"{filename}.{format_type}"
    
    # Avoid overwrites
    counter = 1
    while filepath.exists():
        filepath = output_dir / f"{filename}_{counter}.{format_type}"
        counter += 1
    
    filepath.write_text(content, encoding='utf-8')
    return filepath


def copy_to_clipboard(text):
    """Copy to clipboard if available"""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except:
        return False


def success(msg):
    click.echo(click.style(f"✓ {msg}", fg='green', bold=True))


def info(msg):
    click.echo(click.style(f"  {msg}", fg='cyan'))


def header(msg):
    click.echo()
    click.echo(click.style("━" * 60, fg='blue'))
    click.echo(click.style(f"  {msg}", fg='blue', bold=True))
    click.echo(click.style("━" * 60, fg='blue'))
    click.echo()


def preview_content(content, lines=10):
    """Show preview of content"""
    preview_lines = content.split('\n')[:lines]
    preview = '\n'.join(preview_lines)
    
    click.echo(click.style("\nPreview:", fg='yellow'))
    click.echo(click.style("─" * 60, fg='yellow'))
    click.echo(preview)
    total_lines = len(content.split('\n'))
    if total_lines > lines:
        click.echo(click.style(f"... ({total_lines - lines} more lines)", fg='yellow', dim=True))
    click.echo(click.style("─" * 60, fg='yellow'))


@click.command()
def main():
    """
    🔍 Web Scraper - Premium Interactive Experience
    
    No flags, no complexity - just scrape what you need.
    """
    
    config = load_config()
    
    # Welcome
    header("🔍 WEB SCRAPER")
    
    # Main menu
    click.echo("What would you like to do?\n")
    click.echo("  1. Scrape a single URL")
    click.echo("  2. Scrape multiple URLs from a file")
    click.echo("  3. Extract specific data (emails, phones, etc.)")
    click.echo("  4. Quick scrape (just text, fastest)")
    click.echo("  5. Settings")
    click.echo("  6. Exit")
    
    choice = click.prompt("\nYour choice", type=int, default=1)
    
    if choice == 1:
        scrape_single(config)
    elif choice == 2:
        scrape_batch(config)
    elif choice == 3:
        extract_data(config)
    elif choice == 4:
        quick_mode(config)
    elif choice == 5:
        settings_menu(config)
    elif choice == 6:
        click.echo("\n👋 Goodbye!\n")
        sys.exit(0)
    else:
        click.echo("Invalid choice")
        sys.exit(1)


def scrape_single(config):
    """Scrape a single URL with smart defaults"""
    header("SCRAPE SINGLE URL")
    
    url = click.prompt("Enter URL").strip()
    
    if not url.startswith('http'):
        url = 'https://' + url
    
    # Ask what they want to do with it
    click.echo("\nWhat do you want to do with the content?\n")
    click.echo("  1. Save to file (recommended)")
    click.echo("  2. Copy to clipboard")
    click.echo("  3. Just show me")
    click.echo("  4. Save AND copy to clipboard")
    
    action = click.prompt("\nYour choice", type=int, default=1)
    
    # Ask about format
    click.echo("\nFormat:\n")
    click.echo("  1. Clean text (best for reading)")
    click.echo("  2. Markdown (best for notes)")
    click.echo("  3. LLM-ready (best for AI/Claude)")
    
    format_choice = click.prompt("\nYour choice", type=int, default=2)
    
    # Scrape
    click.echo()
    with click.progressbar(length=100, label='Scraping') as bar:
        bar.update(30)
        
        if format_choice == 3:
            content = extract_article_for_llm(url)
        else:
            content = scrape_article(url)
        
        bar.update(70)
    
    if not content:
        click.echo(click.style("\n✗ Failed to extract content", fg='red'))
        sys.exit(1)
    
    click.echo(click.style(f"\n✓ Scraped {len(content)} characters", fg='green'))
    
    # Handle based on action
    if action in [1, 4]:  # Save to file
        ext = "md" if format_choice == 2 else "txt"
        filepath = auto_save_content(content, url, config, ext)
        success(f"Saved to: {filepath}")
    
    if action in [2, 4]:  # Copy to clipboard
        if copy_to_clipboard(content):
            success("Copied to clipboard")
        else:
            click.echo(click.style("⚠ Clipboard not available (install: pip install pyperclip)", fg='yellow'))
    
    if action == 3:  # Show
        preview_content(content, 20)
    
    # Ask if they want to do another
    click.echo()
    if click.confirm("Scrape another URL?", default=False):
        scrape_single(config)
    else:
        click.echo("\n✨ Done!\n")


def scrape_batch(config):
    """Batch scrape with wizard"""
    header("BATCH SCRAPE")
    
    # Ask for file or paste URLs
    click.echo("How do you want to provide URLs?\n")
    click.echo("  1. I have a text file with URLs")
    click.echo("  2. Let me paste/type them now")
    
    source = click.prompt("\nYour choice", type=int, default=1)
    
    urls = []
    
    if source == 1:
        file_path = click.prompt("Path to file with URLs").strip()
        try:
            urls = Path(file_path).read_text().strip().split('\n')
            urls = [u.strip() for u in urls if u.strip() and not u.startswith('#')]
        except Exception as e:
            click.echo(click.style(f"\n✗ Error reading file: {e}", fg='red'))
            sys.exit(1)
    else:
        click.echo("\nPaste URLs (one per line, press Enter twice when done):\n")
        while True:
            url = input().strip()
            if not url:
                break
            urls.append(url)
    
    if not urls:
        click.echo(click.style("\n✗ No URLs provided", fg='red'))
        sys.exit(1)
    
    click.echo(f"\n✓ Found {len(urls)} URLs to scrape")
    
    # Ask about output
    output_dir = click.prompt(
        "\nSave to folder",
        default=config['default_output_dir']
    )
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Scrape
    click.echo()
    success_count = 0
    
    with click.progressbar(urls, label='Scraping URLs') as url_list:
        for i, url in enumerate(url_list):
            try:
                content = scrape_article(url)
                if content:
                    filename = f"{i+1:03d}_{clean_filename(url)}.md"
                    filepath = output_path / filename
                    filepath.write_text(content, encoding='utf-8')
                    success_count += 1
            except:
                pass
    
    click.echo()
    success(f"Scraped {success_count}/{len(urls)} URLs to {output_dir}")
    click.echo()


def extract_data(config):
    """Extract specific data patterns"""
    header("EXTRACT DATA")
    
    url = click.prompt("Enter URL").strip()
    
    if not url.startswith('http'):
        url = 'https://' + url
    
    # What to extract
    click.echo("\nWhat do you want to extract?\n")
    click.echo("  1. Email addresses")
    click.echo("  2. Phone numbers")
    click.echo("  3. All URLs/links")
    click.echo("  4. Everything")
    
    choice = click.prompt("\nYour choice", type=int, default=4)
    
    results = {}
    
    click.echo()
    with click.progressbar(length=100, label='Extracting') as bar:
        bar.update(30)
        
        if choice in [1, 4]:
            emails = scrape_with_extraction(url, 'emails')
            results['emails'] = emails
            bar.update(20)
        
        if choice in [2, 4]:
            phones = scrape_with_extraction(url, 'phones')
            results['phones'] = phones
            bar.update(20)
        
        if choice in [3, 4]:
            urls = scrape_with_extraction(url, 'urls')
            results['urls'] = urls
            bar.update(30)
    
    # Show results
    click.echo()
    for key, values in results.items():
        click.echo(click.style(f"\n{key.upper()}:", fg='yellow', bold=True))
        if values:
            for item in values[:20]:  # Show first 20
                click.echo(f"  • {item}")
            if len(values) > 20:
                click.echo(click.style(f"  ... and {len(values) - 20} more", fg='yellow', dim=True))
        else:
            click.echo(click.style("  None found", fg='red', dim=True))
    
    # Save option
    click.echo()
    if click.confirm("Save results to file?", default=True):
        output_file = Path(config['default_output_dir']) / f"{clean_filename(url)}_extracted.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(results, indent=2))
        success(f"Saved to: {output_file}")
    
    click.echo()


def quick_mode(config):
    """Quick scrape mode"""
    header("QUICK SCRAPE")
    
    url = click.prompt("Enter URL").strip()
    
    if not url.startswith('http'):
        url = 'https://' + url
    
    click.echo()
    with click.progressbar(length=100, label='Scraping') as bar:
        bar.update(50)
        content = quick_scrape(url)
        bar.update(50)
    
    if content:
        click.echo()
        preview_content(content, 30)
        
        click.echo()
        if click.confirm("Save this?", default=True):
            filepath = auto_save_content(content, url, config, "txt")
            success(f"Saved to: {filepath}")
    else:
        click.echo(click.style("\n✗ No content extracted", fg='red'))
    
    click.echo()


def settings_menu(config):
    """Settings configuration"""
    header("SETTINGS")
    
    click.echo(f"Current settings:\n")
    click.echo(f"  Default save folder: {config['default_output_dir']}")
    click.echo(f"  Auto-save: {config['auto_save']}")
    click.echo(f"  Default format: {config['default_format']}")
    
    click.echo("\n1. Change default save folder")
    click.echo("2. Reset to defaults")
    click.echo("3. Back to main menu")
    
    choice = click.prompt("\nYour choice", type=int, default=3)
    
    if choice == 1:
        new_dir = click.prompt("New default folder", default=config['default_output_dir'])
        config['default_output_dir'] = new_dir
        save_config(config)
        success("Settings saved")
    elif choice == 2:
        config = {
            "default_output_dir": str(Path.home() / "Downloads" / "scraped"),
            "auto_save": True,
            "default_format": "markdown",
            "copy_to_clipboard": False
        }
        save_config(config)
        success("Reset to defaults")
    
    click.echo()
    main()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        click.echo("\n\n👋 Goodbye!\n")
        sys.exit(0)

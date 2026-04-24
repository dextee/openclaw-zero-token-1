"""Tech stack detection from website HTML.

Detects CMS, CRM, analytics, payment, hosting, and marketing technologies
by scanning HTTP response headers and HTML body content.
"""

import re
import warnings

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TECH_SIGNATURES = {
    "Shopify": ["cdn.shopify.com", "myshopify.com", "Shopify.theme"],
    "WooCommerce": ["woocommerce", "wc-ajax"],
    "Magento": ["Mage.Cookies", "magento"],
    "PrestaShop": ["prestashop"],
    "WordPress": ["wp-content/", "wp-includes/", "wp-json"],
    "Wix": ["wixstatic.com", "_wix_browser_deprecated"],
    "Squarespace": ["squarespace.com", "static1.squarespace"],
    "Webflow": ["webflow.com", "Webflow.require"],
    "HubSpot": ["hs-scripts.com", "hubspot.com/hs/hsstatic"],
    "Salesforce": ["salesforce.com", "pardot.com", "force.com"],
    "Zoho CRM": ["zoho.com/crm", "zohopublic.com"],
    "Freshdesk": ["freshdesk.com", "freshwidget"],
    "Intercom": ["intercom.io", "widget.intercom.io"],
    "Zendesk": ["zendesk.com", "zopim.com"],
    "Mailchimp": ["list-manage.com", "mailchimp.com"],
    "Klaviyo": ["klaviyo.com", "static.klaviyo"],
    "Sendgrid": ["sendgrid.net"],
    "Xero": ["xero.com/api", "go.xero.com"],
    "QuickBooks": ["qbo.intuit.com", "intuit.com"],
    "Stripe": ["js.stripe.com", "stripe.com/v3"],
    "PayPal": ["paypal.com/sdk", "paypalobjects.com"],
    "Google Analytics": ["gtag/js?id=G-", "gtag/js?id=UA-", "google-analytics.com"],
    "Google Ads": ["gtag/js?id=AW-", "googleadservices.com"],
    "Facebook Pixel": ["fbevents.js", "connect.facebook.net/en"],
    "TikTok Pixel": ["analytics.tiktok.com"],
    "Hotjar": ["hotjar.com", "static.hotjar"],
    "Cloudflare": ["cloudflare.com", "__cf_bm"],
    "AWS": ["aws.amazon.com", "amazonaws.com", "cloudfront.net"],
    "Microsoft Azure": ["azurewebsites.net", "azure.com"],
    "Google Cloud": ["storage.googleapis.com", "run.app"],
    "Calendly": ["calendly.com/assets", "assets.calendly"],
    "WhatsApp Business Widget": ["wa.me", "api.whatsapp.com/send"],
}


def detect_tech_stack(url: str, timeout: int = 8) -> list:
    """Detect technologies used by a website.

    Makes a GET request and scans response headers and HTML body
    for known technology signatures. Returns list of detected tech names.
    """
    if not url:
        return []
    if not url.startswith("http"):
        url = "https://" + url

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SG-Enrich/1.0)"},
            timeout=timeout,
            allow_redirects=True,
            verify=False,
        )
        text = resp.text.lower()
        headers_text = str(resp.headers).lower()
        combined = text + "\n" + headers_text

        detected = []
        for tech, signatures in TECH_SIGNATURES.items():
            for sig in signatures:
                if sig.lower() in combined:
                    detected.append(tech)
                    break

        return detected[:15]
    except Exception:
        return []

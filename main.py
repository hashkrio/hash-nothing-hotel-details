from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import uvicorn
import re
import json

app = FastAPI()

class HotelRequest(BaseModel):
    url: str

@app.post("/scrape-hotel")
def scrape_hotel(request: HotelRequest):
    url = request.url
    
    # TripAdvisor blocks simple python scripts, so we must pretend to be a real Chrome browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Failed to fetch page. Status code: {response.status_code}")

        soup = BeautifulSoup(response.content, "html.parser")

        # --- 1. Hotel Name (Cleaned) ---
        hotel_name = "N/A"
        h1_tag = soup.find("h1", {"id": "HEADING"})
        
        if h1_tag:
            # CLEANUP: Remove the "Claimed" badge/tooltip logic BEFORE getting text
            # Find and destroy the badge/tooltip element
            junk_badge = h1_tag.find(attrs={"data-automation": "listingBadgeTooltip"})
            if junk_badge:
                junk_badge.decompose()  # This deletes the tag from the HTML tree completely
            
            # Also remove any standalone SVGs (icons) inside the H1
            for icon in h1_tag.find_all("svg"):
                icon.decompose()

            # Now extract only the remaining text
            hotel_name = h1_tag.get_text(strip=True)
        
        # --- 2. Hotel Description (Targeting About Tab first) ---
        description = "N/A"
        
        # Priority 1: Look for the specific "About" tab container
        about_tab = soup.find(attrs={"data-automation": "aboutTabDescription"})
        if about_tab:
            # Get text with separator to prevent words merging across divs
            description = about_tab.get_text(separator=" ", strip=True)
            # Remove common "Read more" link text if captured
            description = description.replace("Read more", "").strip()
        
        # Priority 2: Fallback to Meta tag if the specific tab isn't found
        if description == "N/A" or not description:
            meta_desc = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta_desc:
                description = meta_desc.get("content", "").strip()

        # --- 3. Contact Number ---
        contact_number = "N/A"
        # Look for <a href="tel:+91...">
        phone_link = soup.find("a", href=re.compile(r"^tel:"))
        if phone_link:
            contact_number = phone_link.get("href").replace("tel:", "")
        else:
            # Look for scripts containing phone numbers
            script_content = soup.find(string=re.compile(r"telephone"))
            if script_content:
                # Try to regex extract a phone number pattern
                phone_match = re.search(r'"telephone":"([^"]+)"', script_content)
                if phone_match:
                    contact_number = phone_match.group(1)

        # --- 4. Rating ---
        rating = "N/A"
        # Look for the bubble rating usually found near the top
        rating_tag = soup.find("span", {"class": "uwJeR"}) # Common class for the number like "5.0"
        if not rating_tag:
            # Fallback: Look for text pattern X.X of 5 bubbles
            text_rating = soup.find(string=re.compile(r"\d\.\d of 5 bubbles"))
            if text_rating:
                rating = text_rating.split(" ")[0]
        else:
            rating = rating_tag.text.strip()

        # --- 5. Review Count (Targeted) ---
        review_count = "N/A"
        # Look for the element with the specific automation tag
        review_tag = soup.find(attrs={"data-automation": "bubbleReviewCount"})

        if review_tag:
            # Text will look like "(833 reviews)"
            text = review_tag.text.strip()
            # Use Regex to extract only the numbers (handles commas like 1,000)
            match = re.search(r'([\d,]+)', text)
            if match:
                review_count = match.group(1).replace(",", "") 

        # --- 6. MAIN IMAGES (High Quality Only) ---
        images = []
        # Find all images
        img_tags = soup.find_all("img")
        
        for img in img_tags:
            # TripAdvisor often puts the real URL in data-lazyurl or data-src to prevent load lag
            src = img.get("data-lazyurl") or img.get("data-src") or img.get("src")
            
            if src and "media/photo-" in src:
                # 1. Filter out user avatars, icons, and map markers
                if any(x in src for x in ["avatar", "logo", "icon", "map_pin", ".svg", "blank.gif"]):
                    continue

                # 2. Logic to get High Res
                # URLs look like: https://media-cdn.tripadvisor.com/media/photo-s/29/08/...jpg
                # We try to force 'photo-w' (wide) for better quality
                high_res_src = re.sub(r'/media/photo-[sflmt]/', '/media/photo-w/', src)
                
                # Clean URL (remove query parameters like ?w=50&h=50)
                if "?" in high_res_src:
                    high_res_src = high_res_src.split("?")[0]

                if high_res_src not in images:
                    images.append(high_res_src)
            
            # 3. Stop after grabbing the main hero images (usually top 10)
            if len(images) >= 10:
                break

        return {
            "status": "success",
            "data": {
                "hotel_name": hotel_name,
                "hotel_description": description,
                "contact_number": contact_number,
                "hotel_review_rating": rating,
                "total_review_count": review_count,
                "images": images
            }
        }

    except Exception as e:
        print(f"Error scraping hotel: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
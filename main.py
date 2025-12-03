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

        # --- 1. Hotel Name ---
        # TripAdvisor usually puts the name in an H1 tag with id 'HEADING'
        hotel_name = "N/A"
        h1_tag = soup.find("h1", {"id": "HEADING"})
        if h1_tag:
            hotel_name = h1_tag.text.strip()
        
        # --- 2. Hotel Description ---
        # The easiest way to get the description on TA is the meta tag, 
        # because the on-page text is often hidden behind a "Read more" button using JS.
        description = "N/A"
        meta_desc = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
        if meta_desc:
            description = meta_desc.get("content", "").strip()

        # --- 3. Rating & 4. Review Count ---
        # TripAdvisor classes are dynamic (random letters), so we look for structure or aria-labels.
        rating = "N/A"
        review_count = "N/A"

        # Attempt to find the specific review section
        # Look for the bubble rating usually found near the top
        rating_tag = soup.find("span", {"class": "uwJeR"}) # Common class for the number like "5.0"
        if not rating_tag:
            # Fallback: Look for text pattern X.X of 5 bubbles
            text_rating = soup.find(string=re.compile(r"\d\.\d of 5 bubbles"))
            if text_rating:
                rating = text_rating.split(" ")[0]
        else:
            rating = rating_tag.text.strip()

        # Look for review count
        count_tag = soup.find("span", string=re.compile(r"reviews"))
        if count_tag:
            text = count_tag.text
            # Extract numbers from "880 reviews" -> "880"
            numbers = re.findall(r'[\d,]+', text)
            if numbers:
                review_count = numbers[0].replace(",", "")

        # --- 5. Images ---
        images = []
        # Find images in the photo grid or gallery
        # TA creates dynamic classes, so we look for img tags with large dimensions or specific container patterns
        
        # Strategy: Look for all images, filter for high res (usually source contains 'photo-')
        all_imgs = soup.find_all("img")
        
        for img in all_imgs:
            src = img.get("src")
            # TripAdvisor images often have 'media' or 'photo' in URL. 
            # We exclude small generic icons like 'blank.gif' or 'svg'
            if src and "http" in src and (".jpg" in src or ".jpeg" in src):
                if "w=50" not in src and "logo" not in src and "avatar" not in src:
                     # Attempt to get higher resolution if available in data-lazyload-src
                    high_res = img.get("data-lazyurl") or img.get("data-src") or src
                    if high_res not in images:
                        images.append(high_res)
            
            if len(images) >= 10:
                break

        return {
            "status": "success",
            "data": {
                "Hotel Name": hotel_name,
                "Hotel Description": description,
                "Hotel review rating": rating,
                "Total review count": review_count,
                "images": images
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
# project_root/main.py
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pydantic import BaseModel
import asyncio
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.action_chains import ActionChains
from bs4 import BeautifulSoup
import time
import os
import datetime # For unique filenames
import io

app = FastAPI()

# --- Configuration for Serving Frontend ---
# Mount static files (CSS, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configure Jinja2Templates to serve HTML files
templates = Jinja2Templates(directory="templates")

# Configure CORS (still needed for cross-origin if frontend HTML is loaded from different origin, though less likely now)
origins = [
    "http://localhost", # Adjust if your frontend is on a different domain/port
    "http://localhost:8000", # Default FastAPI port
    # Add your Render frontend URL here when deploying, e.g., "https://your-frontend-url.onrender.com"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define a directory for saved CSV files
DOWNLOADS_DIR = "downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True) # Create the directory if it doesn't exist

# --- Pydantic Model (unchanged) ---
class JobSearchRequest(BaseModel):
    username: str
    password: str
    skill: str

# In your run_naukri_scraper function in main.py
async def run_naukri_scraper(username: str, password: str, skill: str):
    # ... (existing code)

    try:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Add these arguments for headless Chrome in Docker
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")
        options.add_argument("--proxy-server='direct://'")
        options.add_argument("--proxy-bypass-list=*")
        
        options.binary_location = os.environ.get("GOOGLE_CHROME_BIN", "/usr/bin/google-chrome") # Use environment variable
        # Use ChromeDriverManager.install() for the driver itself
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 15)
        # ... rest of your scraping logic
        # Ensure Chrome driver path is correct or managed by webdriver_manager
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        wait = WebDriverWait(driver, 15)

        # Login to Naukri
        driver.get('https://www.naukri.com/mnjuser/login')
        email_input = wait.until(EC.presence_of_element_located((By.XPATH, '/html/body/div[3]/div/div/div/div/div/div/div/div[2]/div/form/div[2]/div[1]/div/input')))
        email_input.send_keys(username)
        password_input = driver.find_element(By.XPATH, '/html/body/div[3]/div/div/div/div/div/div/div/div[2]/div/form/div[2]/div[2]/div/input')
        password_input.send_keys(password)
        login_button = driver.find_element(By.XPATH, '/html/body/div[3]/div/div/div/div/div/div/div/div[2]/div/form/div[2]/div[3]/div/button[1]')
        login_button.click()

        try:
            wait.until(EC.url_changes('https://www.naukri.com/mnjuser/login'))
            print("Login successful.")
        except:
            print("Login failed or took too long.")
            return {"status": "error", "message": "Login failed. Please check your credentials."}

        # Go to job search page
        time.sleep(3)
        driver.get('https://www.naukri.com/jobs')
        search_input = wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'suggestor-input')))
        driver.execute_script("arguments[0].click();", search_input)
        time.sleep(2)
        actions = ActionChains(driver)
        actions.move_to_element(search_input).click().send_keys(skill).send_keys(Keys.RETURN).perform()
        time.sleep(5)

        main_window = driver.current_window_handle

        while True:
            soup = BeautifulSoup(driver.page_source, 'lxml')
            postings = soup.find_all('div', class_='srp-jobtuple-wrapper')

            if not postings:
                print("❌ No job postings found on this page.")
                break

            for post in postings:
                try:
                    link = post.find('a', class_='title').get('href')
                    name = post.find('a', class_='title').text.strip()
                    com_name = post.find('a', 'comp-name').text.strip() if post.find('a', 'comp-name') else 'Not Found'
                    experience = post.find('span', class_='expwdth').text.strip() if post.find('span', 'expwdth') else 'Not Mentioned'
                    salary_tag = post.find('span', class_='sal')
                    salary = salary_tag.find('span').text.strip() if salary_tag and salary_tag.find('span') else 'Not Mentioned'
                    location = post.find('span', class_='locWdth').text.strip() if post.find('span', 'locWdth') else 'Not Mentioned'
                    key_skills_section = post.find('div', class_='styles_key-skill__GIPn_')
                    key_skills = ", ".join([skill_elem.text.strip() for skill_elem in key_skills_section.find_all('span')]) if key_skills_section else 'Not Mentioned'

                    job_list.append({
                        'Link': link,
                        'Name': name,
                        'Com_name': com_name,
                        'Experience': experience,
                        'Salary': salary,
                        'Location': location,
                        'Key_Skills': key_skills
                    })

                    driver.execute_script(f"window.open('{link}', '_blank');")
                    driver.switch_to.window(driver.window_handles[-1])

                    try:
                        apply_btn = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, '//button[contains(text(), "Apply") or contains(text(), "Apply Now")]'))
                        )
                        apply_btn.click()
                        print(f"✅ Applied to: {name}")
                    except Exception as e:
                        print(f"⚠️ Could not apply: {name} — {e}")

                    all_tabs = driver.window_handles
                    if len(all_tabs) > 10:
                        tabs_to_close = all_tabs[-6:]
                        for t in tabs_to_close:
                            if t != main_window:
                                driver.switch_to.window(t)
                                driver.close()
                        print("🧹 Closed last 6 tabs to manage window count.")
                        driver.switch_to.window(main_window)
                    else:
                        driver.switch_to.window(main_window)

                except Exception as e:
                    print(f"❌ Skipping job due to error: {e}")

            try:
                # First attempt with existing XPath selectors
                next_button = None
                try:
                    next_button = driver.find_element(By.XPATH, '//a[@aria-label="Next"] | //a[contains(@class, "styles_next-tab__6rB6b")] | //a[text()="Next"]')
                except:
                    pass # Continue to try the next selector if this one fails

                # Second attempt with the new CSS selector
                if not next_button:
                    try:
                        next_button = driver.find_element(By.CSS_SELECTOR, '#lastCompMark > a:nth-child(4)')
                    except:
                        pass # Continue if this also fails

                if next_button and 'disabled' not in next_button.get_attribute('class'):
                    next_button.click()
                    time.sleep(5) # Give time for the next page to load
                else:
                    print("✅ Next button is disabled or not found using available selectors. No more pages.")
                    break
            except Exception as e:
                print(f"✅ No more pages or next button not found: {e}. Scraping complete.")
                break

        df = pd.DataFrame(job_list)
        if not df.empty:
            # --- MODIFICATION START ---
            # Use a fixed filename instead of a timestamped one
            generated_filename = f"naukri_jobs_{skill.replace(' ', '_')}.csv" # Sanitize skill for filename
            file_path = os.path.join(DOWNLOADS_DIR, generated_filename)
            df.to_csv(file_path, index=False) # This will overwrite the file if it exists
            # --- MODIFICATION END ---
            print(f"CSV saved to: {file_path}")
            return {"status": "success", "message": f"Scraping complete. Applied to {len(job_list)} jobs.", "jobs_applied": len(job_list), "job_data": df.to_dict(orient='records'), "filename": generated_filename}
        else:
            return {"status": "success", "message": "Scraping complete. No jobs found.", "jobs_applied": 0, "job_data": [], "filename": None}

    except Exception as e:
        print(f"An error occurred during the scraping process: {e}")
        return {"status": "error", "message": f"An error occurred: {str(e)}", "filename": None}
    finally:
        if 'driver' in locals() and driver:
            driver.quit()

# --- API Endpoints (unchanged logic) ---
@app.post("/start-scraper/")
async def start_scraper(request: JobSearchRequest):
    result = await run_naukri_scraper(request.username, request.password, request.skill)
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["message"])
    return result

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(DOWNLOADS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=file_path, filename=filename, media_type='text/csv')

@app.head("/", status_code=200) # Add this line
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serves the main HTML page."""
    # For HEAD requests, FastAPI will automatically send the headers without the body.
    # The return value from templates.TemplateResponse will still ensure correct headers for GET.
    return templates.TemplateResponse("index.html", {"request": request})

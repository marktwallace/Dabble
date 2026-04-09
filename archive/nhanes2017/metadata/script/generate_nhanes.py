# This script generates YAML metadata files for NHANES laboratory data files.
# Run with: python script/generate_nhanes.py
import os
import requests
import yaml
import json
from pathlib import Path
from typing import Dict, List
from bs4 import BeautifulSoup
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser

URL_BASE = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/"
DOCFILE_EXT = ".htm"
DATAFILE_EXT = ".xpt"

def load_component_files(component_json: str) -> Dict[str, str]:
    """Load the component file mappings from JSON"""
    with open(component_json, 'r') as f:
        return json.load(f)

def fetch_doc_content(url: str) -> str:
    """Fetch and parse the documentation HTML"""
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    # Extract main content, removing navigation and other unnecessary elements
    main_content = soup.find('div', {'class': 'body-content'})
    if main_content:
        return main_content.get_text(separator='\n', strip=True)
    return soup.get_text(separator='\n', strip=True)

def generate_json_summary(doc_content: str, llm: ChatOpenAI) -> Dict:
    """Generate a JSON summary of the documentation using LLM"""
    system_prompt = open("prompts/docfile_html_to_json.txt", "r").read()
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Please analyze this NHANES documentation and create a JSON summary:\n\n{doc_content}")
    ]
    
    response = llm.invoke(messages)
    # Parse the response as JSON
    try:
        return json.loads(response.content)
    except json.JSONDecodeError:
        # If the response isn't valid JSON, try to extract JSON portion
        json_start = response.content.find('{')
        json_end = response.content.rfind('}') + 1
        if json_start >= 0 and json_end > json_start:
            return json.loads(response.content[json_start:json_end])
        raise

def main():
    # Initialize LLM
    llm = ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0)
    
    # Load component files
    components = {}
    metadata_dir = Path(__file__).parent.parent
    for component_file in metadata_dir.glob('source/component/*.json'):
        component_name = component_file.stem
        components[component_name] = load_component_files(str(component_file))
    
    # Process each component
    for component_name, file_mappings in components.items():
        output_dir = metadata_dir / 'processed' / component_name.lower()
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for doc_code, description in file_mappings.items():
            doc_url = f"{URL_BASE}{doc_code}{DOCFILE_EXT}"
            print(f"Processing {doc_code}...")
            #print(doc_url)
            #continue
            
            try:
                # Fetch and process documentation
                doc_content = fetch_doc_content(doc_url)
                json_summary = generate_json_summary(doc_content, llm)
                
                # Save JSON summary
                output_file = output_dir / f"{doc_code}.json"
                with open(output_file, 'w') as f:
                    json.dump(json_summary, f, indent=2)
                print(f"Saved summary to {output_file}")
                
            except Exception as e:
                print(f"Error processing {doc_code}: {str(e)}")
                continue

if __name__ == "__main__":
    main()





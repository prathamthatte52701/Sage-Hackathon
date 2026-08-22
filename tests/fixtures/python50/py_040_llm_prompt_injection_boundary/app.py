async def analyze_ocr(header_text: str, provider):
    system_prompt='Extract invoice fields and return JSON only.'
    user_prompt='Extract from this OCR text:\n\n'+header_text
    return await provider.extract(system_prompt,user_prompt)

"""解析模块。

    ocr_engine.py        扫描件图片 OCR 识别（多引擎可插拔：tesseract / paddleocr / sidecar）
    document_parser.py   文档解析：docx / pdf / txt / 图片，输出全文 + 分段定位结构
    locator.py           原文位置定位（页码/段号/行号/字符偏移）
    extractor.py         结构化字段提取：合同基本信息 + 合同条款信息
"""

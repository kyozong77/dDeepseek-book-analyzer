#!/usr/bin/env python3
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

def create_pdf(filename):
    c = canvas.Canvas(filename, pagesize=letter)
    c.setFont("Helvetica", 12)
    
    # Add title
    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, 750, "Test Book Title")
    
    # Add author
    c.setFont("Helvetica", 12)
    c.drawString(100, 720, "Author: Test Author")
    
    # Add some paragraphs of content
    text = [
        "Chapter 1: Introduction",
        "",
        "This is a test book created for testing the DeepSeek processor script.",
        "It contains some sample text that will be processed by the DeepSeek API.",
        "The goal is to generate an analysis of this content and translate it.",
        "",
        "The book explores various concepts related to artificial intelligence and",
        "machine learning, focusing on how these technologies are changing our world.",
        "",
        "Key concepts discussed include deep learning, neural networks, and natural",
        "language processing. The applications of these technologies span across",
        "various industries including healthcare, finance, and education."
    ]
    
    y = 690
    for line in text:
        if line == "":
            y -= 15  # Empty line for paragraph spacing
        else:
            c.drawString(100, y, line)
            y -= 15
    
    # Add another chapter
    c.setFont("Helvetica-Bold", 14)
    y -= 20
    c.drawString(100, y, "Chapter 2: Deep Learning Fundamentals")
    c.setFont("Helvetica", 12)
    
    y -= 20
    chapter2_text = [
        "Deep learning is a subset of machine learning that uses neural networks with",
        "multiple layers. These neural networks attempt to simulate the behavior of",
        "the human brain—albeit far from matching its ability—allowing it to learn",
        "from large amounts of data.",
        "",
        "While a neural network with a single layer can still make approximate predictions,",
        "additional hidden layers can help optimize and refine for accuracy.",
        "",
        "Deep learning drives many artificial intelligence (AI) applications and services",
        "that improve automation, performing analytical and physical tasks without",
        "human intervention. This technology is currently being applied to many",
        "industries including automotive, healthcare, finance, and manufacturing."
    ]
    
    for line in chapter2_text:
        if line == "":
            y -= 15  # Empty line for paragraph spacing
        else:
            c.drawString(100, y, line)
            y -= 15
    
    c.showPage()  # Add a new page
    
    # Add more content to the second page
    c.setFont("Helvetica-Bold", 14)
    c.drawString(100, 750, "Chapter 3: Applications and Case Studies")
    c.setFont("Helvetica", 12)
    
    y = 720
    chapter3_text = [
        "The applications of deep learning are vast and diverse. Here are some",
        "notable examples from different industries:",
        "",
        "Healthcare: Deep learning algorithms can detect patterns in medical images",
        "like X-rays, MRIs, and CT scans, helping to identify diseases at earlier stages.",
        "",
        "Finance: Financial institutions use deep learning for fraud detection,",
        "risk management, and algorithmic trading strategies.",
        "",
        "Education: Adaptive learning platforms leverage deep learning to personalize",
        "educational content based on student performance and engagement.",
        "",
        "Transportation: Self-driving vehicles rely on deep learning to interpret",
        "sensor data and make real-time decisions on the road.",
        "",
        "These examples illustrate how deep learning is transforming industries and",
        "creating new possibilities for innovation and efficiency.",
    ]
    
    for line in chapter3_text:
        if line == "":
            y -= 15  # Empty line for paragraph spacing
        else:
            c.drawString(100, y, line)
            y -= 15
    
    c.save()

if __name__ == "__main__":
    create_pdf("test_book.pdf")
    print("Test PDF created successfully: test_book.pdf")

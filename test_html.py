import json
from html_img_engine import generate_image_from_html
from pathlib import Path

payload = {
  "width": 1080,
  "height": 1920,
  "Images": [
    {
      "html": "\n<div class=\"container\">\n  <p class=\"error-text\">\n    <span class=\"emoji\">❌</span> I will sleep late today\n  </p>\n  <p class=\"meaning-text\">\n    when you mean: vou dormir tarde\n  </p>\n</div>\n",
      "css": "\n@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@700&family=Roboto:wght@400&display=swap');\n\nbody {\n  margin: 0;\n  padding: 0;\n  box-sizing: border-box;\n  font-family: 'Poppins', sans-serif;\n}\n\n.container {\n  width: 1080px;\n  height: 1920px;\n  background-color: #1A1A1A;\n  display: flex;\n  flex-direction: column;\n  justify-content: center;\n  align-items: center;\n  padding: 50px;\n}\n\n.error-text {\n  color: #FFFFFF;\n  font-size: 100px;\n  font-weight: 700;\n  text-align: center;\n  line-height: 1.2;\n  margin: 0;\n}\n\n.emoji {\n  font-size: 100px;\n}\n\n.meaning-text {\n  color: #BDBDBD;\n  font-family: 'Roboto', sans-serif;\n  font-size: 60px;\n  font-weight: 400;\n  text-align: center;\n  margin-top: 40px;\n}\n"
    }
  ]
}

generate_image_from_html(
    payload["Images"][0]["html"],
    payload["Images"][0]["css"],
    payload["width"],
    payload["height"],
    Path("test_output.png")
)

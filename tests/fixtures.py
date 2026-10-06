import zipfile
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
pdfmetrics.registerFont(TTFont('DV', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
c = canvas.Canvas('ru.pdf')
para = "В начале было Слово, и Слово было у Бога, и Слово было Бог. Оно было в начале у Бога. Все через Него начало быть, и без Него ничто не начало быть, что начало быть."
for page in range(3):
    c.setFont('DV', 11); y = 800
    c.drawString(50, y, f"Глава {page+1}"); y -= 24
    for k in range(12):
        line = para if k % 2 == 0 else "Это пример длинного предложения с перено-"
        c.drawString(50, y, line[:95]); y -= 16
        if k % 2: c.drawString(50, y, "сом слова на следующую строку."); y -= 16
    c.drawString(290, 40, str(page + 1))
    c.showPage()
c.save()

with zipfile.ZipFile('ro.epub', 'w') as z:
    z.writestr('mimetype', 'application/epub+zip')
    z.writestr('META-INF/container.xml', '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
    z.writestr('OEBPS/content.opf', '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest><item id="c2" href="text/ch2.xhtml" media-type="application/xhtml+xml"/><item id="c1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>')
    body = "<p>" + "La început era Cuvântul, și Cuvântul era cu Dumnezeu, și Cuvântul era Dumnezeu. " * 15 + "</p>"
    z.writestr('OEBPS/text/ch1.xhtml', f'<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Capitolul unu</h1>{body}{body}</body></html>')
    z.writestr('OEBPS/text/ch2.xhtml', f'<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Capitolul doi</h1>{body}</body></html>')

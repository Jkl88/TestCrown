from app.pdf_extract import is_pdf


def test_pdf_magic():
    assert is_pdf(b"%PDF-1.4\n%")
    assert not is_pdf(b"PK\x03\x04")
    assert not is_pdf(b"")

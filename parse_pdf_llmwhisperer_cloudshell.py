from pathlib import Path
import os
import sys
import json
import traceback
from dotenv import load_dotenv

from unstract.llmwhisperer import LLMWhispererClientV2
from unstract.llmwhisperer.client_v2 import LLMWhispererClientException


# Cargar .env usando ruta explícita para evitar errores en Cloud Shell
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)


LLMWHISPERER_KEYS = [
    os.getenv("LLMWHISPERER_API_KEY_1"),
    os.getenv("LLMWHISPERER_API_KEY_2"),
    os.getenv("LLMWHISPERER_API_KEY_3"),
]


def limpiar_texto_para_llm(texto: str) -> str:
    if not texto:
        return ""

    texto = texto.replace("<<<\x0c", "\n\n--- NUEVA PÁGINA ---\n\n")

    # Reducir saltos excesivos de línea
    while "\n\n\n" in texto:
        texto = texto.replace("\n\n\n", "\n\n")

    return texto.strip()


def extraer_texto_pdf_con_llmwhisperer(pdf_path: str) -> dict:
    pdf = Path(pdf_path).expanduser().resolve()

    if not pdf.exists():
        raise FileNotFoundError(f"No existe el archivo PDF: {pdf}")

    if pdf.suffix.lower() != ".pdf":
        raise ValueError(f"El archivo no parece ser PDF: {pdf}")

    available_keys = [
        (index + 1, key)
        for index, key in enumerate(LLMWHISPERER_KEYS)
        if key and key.strip()
    ]

    if not available_keys:
        raise RuntimeError(
            "No se encontró ninguna API key. Revisa el archivo .env."
        )

    last_error = None

    for key_number, api_key in available_keys:
        try:
            print(f"🔑 Usando LLMWHISPERER_API_KEY_{key_number}")
            print(f"📄 Enviando PDF a LLMWhisperer: {pdf.name}")

            client = LLMWhispererClientV2(api_key=api_key)

            result = client.whisper(
                file_path=str(pdf),
                wait_for_completion=True,
                wait_timeout=360,
                mode="high_quality",
                output_mode="layout_preserving",
                lang="spa",
            )

            extraction = result.get("extraction", {})
            result_text = extraction.get("result_text")

            if not result_text:
                raise RuntimeError(
                    "LLMWhisperer respondió, pero no devolvió extraction.result_text"
                )

            texto_limpio = limpiar_texto_para_llm(result_text)

            return {
                "ok": True,
                "pdf": str(pdf),
                "api_key_used": key_number,
                "raw_result": result,
                "text": texto_limpio,
            }

        except LLMWhispererClientException as e:
            status_code = getattr(e, "status_code", None)
            error_text = str(e)

            print(f"⚠️ Error con API key #{key_number}: {error_text}")

            last_error = {
                "key_number": key_number,
                "status_code": status_code,
                "error": error_text,
            }

            # Si una key falla, intentamos con la siguiente
            continue

        except Exception as e:
            print(f"⚠️ Error inesperado con API key #{key_number}: {e}")
            last_error = {
                "key_number": key_number,
                "status_code": None,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
            continue

    return {
        "ok": False,
        "pdf": str(pdf),
        "error": "No se pudo procesar el PDF con ninguna API key disponible.",
        "last_error": last_error,
    }


def guardar_salidas(resultado: dict, output_dir: str = "outputs") -> None:
    output_path = BASE_DIR / output_dir
    output_path.mkdir(parents=True, exist_ok=True)

    pdf_name = Path(resultado["pdf"]).stem

    json_path = output_path / f"{pdf_name}_llmwhisperer_raw.json"
    txt_path = output_path / f"{pdf_name}_llmwhisperer.txt"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    if resultado.get("ok"):
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(resultado["text"])

    print()
    print("✅ Archivos generados:")
    print(f"JSON: {json_path}")

    if resultado.get("ok"):
        print(f"TXT:  {txt_path}")
        print()
        print("✅ Parseo terminado correctamente.")
    else:
        print()
        print("❌ El parseo falló. Revisa el JSON para ver el error.")


def main():
    if len(sys.argv) < 2:
        print("Uso:")
        print("python parse_pdf_llmwhisperer_cloudshell.py archivo.pdf")
        sys.exit(1)

    pdf_path = sys.argv[1]
    resultado = extraer_texto_pdf_con_llmwhisperer(pdf_path)
    guardar_salidas(resultado)

    if not resultado.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()

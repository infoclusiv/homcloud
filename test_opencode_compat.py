"""Compatibilidad de comandos CLI sin invocar servicios remotos."""
import subprocess
from pathlib import Path
from unittest.mock import patch
import unittest

from opencode_compat import crear_comando_opencode, detectar_version_opencode


class OpenCodeCompatTests(unittest.TestCase):
    def test_detectar_version_mayor(self):
        for version, major in (("1.19.5\n", 1), ("2.1.4\n", 2), ("opencode v2.1.5\n", 2)):
            with self.subTest(version=version):
                respuesta = subprocess.CompletedProcess(["opencode", "--version"], 0, stdout=version)
                with patch("opencode_compat.subprocess.run", return_value=respuesta):
                    self.assertEqual(detectar_version_opencode("opencode"), major)

    def test_rechaza_version_desconocida(self):
        for texto in ("x", "3.0.0"):
            respuesta = subprocess.CompletedProcess(["opencode", "--version"], 0, stdout=texto)
            with patch("opencode_compat.subprocess.run", return_value=respuesta):
                with self.assertRaises(RuntimeError):
                    detectar_version_opencode("opencode")

    def test_v1_conserva_dir_sin_enviar_prompts_a_logs(self):
        cmd = crear_comando_opencode(
            "/usr/bin/opencode", 1, "PROMPT PRIVADO",
            modelo="opencode/deepseek-v4.1-flash-free",
            archivo=Path("/tmp/documento.txt"), directorio=Path("/tmp/work"),
        )
        self.assertEqual(cmd[:5], [
            "/usr/bin/opencode", "--print-logs", "--log-level", "WARN", "run",
        ])
        self.assertIn("--dir", cmd)
        self.assertEqual(cmd[-1], "PROMPT PRIVADO")
        self.assertEqual(cmd[cmd.index("--file") + 1], "/tmp/documento.txt")

    def test_v2_aislado_no_usa_dir_antiguo(self):
        cmd = crear_comando_opencode(
            "/usr/bin/opencode", 2, "PROMPT PRIVADO",
            modelo="opencode/glm-5.3-flash-free",
            archivo=Path("/tmp/documento.txt"), directorio=Path("/tmp/work"),
        )
        self.assertEqual(cmd[:3], ["/usr/bin/opencode", "run", "--standalone"])
        self.assertNotIn("--dir", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "opencode/glm-5.3-flash-free")
        self.assertEqual(cmd[-1], "PROMPT PRIVADO")


if __name__ == "__main__":
    unittest.main()

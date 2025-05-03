import os

# Obtém o diretório onde a planilha será salva
spreadsheet_path = "campanhas_lucro_reducao.xlsx"
dir_path = os.path.dirname(os.path.abspath(spreadsheet_path))

# Testa permissão de escrita
try:
    test_file = os.path.join(dir_path, "test_write_permission.txt")
    with open(test_file, "w") as f:
        f.write("Teste de permissão de escrita.")
    os.remove(test_file)
    print("Permissão de escrita OK!")
except Exception as e:
    print(f"[ERRO] Sem permissão de escrita no diretório: {e}")

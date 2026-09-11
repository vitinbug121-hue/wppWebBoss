#!/usr/bin/env python3
"""
Script para configurar a preferência de máquina (cliente/desenvolvedor)
Executa apenas uma vez no início para configurar qual máquina está usando.
"""

import os
import json

def main():
    print("\n" + "="*70)
    print("CONFIGURAÇÃO DE MÁQUINA - SEPARAÇÃO DE AGENDAMENTOS")
    print("="*70 + "\n")
    
    # Determina o diretório base
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pref_file = os.path.join(script_dir, '.machine_preference')
    
    # Verifica se já existe preferência
    if os.path.exists(pref_file):
        with open(pref_file, 'r') as f:
            current = f.read().strip()
        print(f"✓ Máquina atual configurada como: {current}")
        print(f"  Arquivo: {pref_file}\n")
        
        mudar = input("Deseja mudar de máquina? (S/n): ").strip().lower()
        if mudar not in ['s', 'sim', 'y', 'yes']:
            print("\nNenhuma mudança realizada.")
            return
    
    print("\nSelecione qual máquina você está usando:")
    print("  1. Cliente (g:/ ou h:/)")
    print("  2. Desenvolvedor\n")
    
    while True:
        choice = input("Digite 1 ou 2: ").strip()
        if choice == '1':
            machine = 'cliente'
            break
        elif choice == '2':
            machine = 'desenvolvedor'
            break
        else:
            print("Opção inválida. Tente novamente.")
    
    # Salva a preferência
    try:
        with open(pref_file, 'w') as f:
            f.write(machine)
        
        print(f"\n✓ Máquina configurada como: {machine}")
        print(f"  Arquivo de config: agendamentos_config_{machine}.json")
        print(f"  Arquivo de histórico: agendamentos_historico_{machine}.json")
        print(f"\n✓ Preferência salva em: {pref_file}\n")
        
        # Lista arquivos genéricos que podem ser removidos
        generic_files = [
            os.path.join(script_dir, 'agendamentos_config.json'),
            os.path.join(script_dir, 'agendamentos_historico.json'),
        ]
        
        existing_generics = [f for f in generic_files if os.path.exists(f)]
        if existing_generics:
            print("⚠️  Arquivos genéricos encontrados (podem ser removidos):")
            for f in existing_generics:
                print(f"   - {os.path.basename(f)}")
            
            remove = input("\nRemover arquivos genéricos? (S/n): ").strip().lower()
            if remove in ['s', 'sim', 'y', 'yes']:
                for f in existing_generics:
                    try:
                        os.remove(f)
                        print(f"  ✓ Removido: {os.path.basename(f)}")
                    except Exception as e:
                        print(f"  ✗ Erro ao remover {os.path.basename(f)}: {e}")
        
        print("\n" + "="*70)
        print("✓ CONFIGURAÇÃO CONCLUÍDA COM SUCESSO")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\n✗ ERRO ao salvar preferência: {e}")

if __name__ == '__main__':
    main()

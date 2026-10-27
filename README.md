# dicom-stl

Dois scripts em Python para preparar exames de tomografia (TC ou CBCT) antes do planejamento digital em implantodontia.

`anonimizar.py` copia uma série DICOM para outra pasta sem os dados do paciente.
`dicom2stl_osso.py` converte a série em um STL contendo só o osso.

Fiz isso para estudar segmentação de imagem médica e para ter um fluxo reproduzível de linha de comando, sem depender de software fechado na etapa de exportação.

## O que faz

### anonimizar.py

Lê cada `.dcm` da pasta de origem, apaga a identificação e grava a cópia em outra pasta. Os originais não são tocados.

| Item | Ação |
|------|------|
| Grupo (0010,xxxx) inteiro (nome, ID, nascimento, sexo, endereço, telefone, outros IDs) | apagado; PatientName e PatientID recebem o texto de `--id` |
| InstitutionName, InstitutionAddress, ReferringPhysicianName, PerformingPhysicianName, OperatorsName, StationName, AccessionNumber, StudyID, StudyComments, DeviceSerialNumber | esvaziados |
| Datas e horas de estudo, série, aquisição, conteúdo e criação | esvaziadas, a menos que use `--manter-datas` |
| StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID, FrameOfReferenceUID | trocados por UIDs novos, com o mesmo mapeamento em toda a série (a série continua agrupável) |
| Tags privadas do fabricante | removidas |
| Nome do arquivo | renomeado para `ID_0001.dcm`, `ID_0002.dcm`... porque o nome exportado pelo scanner costuma conter o nome do paciente |

Pixels, posição e orientação, espaçamento, rescale e fabricante ficam como estão. É isso que a segmentação precisa.

### dicom2stl_osso.py

Lê a série, separa osso de tecido mole por limiar e gera uma malha STL fechada, em coordenadas do paciente (LPS), pronta para abrir em software de planejamento ou em um slicer de impressão 3D.

## Como o pipeline funciona

Na ordem em que o código executa:

1. Leitura. SimpleITK procura séries DICOM na pasta e nas subpastas. Se houver mais de uma, usa a que tem mais fatias. RescaleSlope e RescaleIntercept são aplicados, então uma TC médica sai em HU.
2. Reamostragem (opcional). `--reamostrar 0.3` interpola o volume para voxel isotrópico de 0,3 mm. Útil quando o espaçamento entre fatias é diferente do espaçamento no plano.
3. Filtro de mediana 3x3x3. Tira o ruído pontual típico de CBCT antes de limiarizar.
4. Limiar de osso. Manual com `--limiar`, ou automático: Otsu de duas classes (tecido mole e osso) calculado só nos voxels acima de -300, que é o corte de ar. Rodar Otsu no volume inteiro não funciona em CBCT dental porque mais de 90% do campo é ar e o algoritmo acaba separando ar de "resto". Se houver mais de 5 milhões de voxels fora do ar, usa uma amostra aleatória com semente fixa.
5. Segmentação. Limiar binário entre `--limiar` e `--limiar-max`. Depois um fechamento morfológico (raio 1) para tapar buracos pequenos e uma abertura (raio 1) para tirar ruído isolado. Com `--ilhas N`, rotula as regiões conectadas por tamanho e mantém as N maiores.
6. Malha. O volume binário ganha uma borda de 1 voxel para a malha fechar nas extremidades. Marching cubes (scikit-image) no nível 0,5 com o espaçamento real. Os vértices voltam para a ordem (x, y, z) em mm e recebem a matriz de direção e a origem do DICOM. Se o determinante da direção for negativo, as normais são invertidas para continuarem apontando para fora.
7. Suavização. Taubin (trimesh), 10 iterações por padrão. Taubin encolhe menos que Laplaciano puro.
8. Redução (opcional). `--reduzir 0.5` tira metade dos triângulos com fast-simplification.
9. Exportação. Grava o STL e imprime número de triângulos, dimensões e se a malha está fechada.

`--info` para logo depois da leitura e imprime percentis, histograma e o limiar Otsu sugerido. Serve para escolher `--limiar` quando o automático erra.

## Instalação

Python 3.10 ou mais novo.

```bash
git clone https://github.com/luanmaciel/dicom-stl.git
cd dicom-stl
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux ou macOS
pip install -r requirements.txt
```

`fast-simplification` só é necessário para `--reduzir`. Sem ele o script avisa e segue sem reduzir.

## Uso

Os dados de exemplo não estão no repositório. Qualquer DICOM precisa ser anonimizado antes de entrar em uma pasta que vá para fora da sua máquina.

Anonimizar uma série:

```bash
python anonimizar.py exames/caso_exemplo exames/caso_exemplo_anon --id paciente01
```

Ver estatísticas do volume antes de escolher o limiar:

```bash
python dicom2stl_osso.py exames/caso_exemplo_anon --info
```

Gerar o STL com limiar automático:

```bash
python dicom2stl_osso.py exames/caso_exemplo_anon saida/osso.stl
```

Limiar manual, cortando metal acima de 2000 e mantendo só a maior ilha:

```bash
python dicom2stl_osso.py exames/caso_exemplo_anon saida/osso.stl --limiar 400 --limiar-max 2000 --ilhas 1
```

Voxel isotrópico, metade dos triângulos e canto do volume em (0,0,0):

```bash
python dicom2stl_osso.py exames/caso_exemplo_anon saida/osso.stl --reamostrar 0.3 --reduzir 0.5 --origem-zero
```

## Parâmetros

### anonimizar.py

| Parâmetro | Padrão | O que faz |
|-----------|--------|-----------|
| `origem` | | pasta com os `.dcm` originais (não é alterada) |
| `destino` | | pasta nova para a cópia; não pode ser a mesma da origem |
| `--id` | `ANON` | texto gravado em PatientName e PatientID e usado no nome dos arquivos |
| `--manter-datas` | desligado | não apaga datas e horas do exame |

### dicom2stl_osso.py

| Parâmetro | Padrão | O que faz |
|-----------|--------|-----------|
| `pasta` | | pasta com os arquivos DICOM (busca em subpastas) |
| `saida` | `osso.stl` | caminho do STL |
| `--limiar` | automático (Otsu) | limiar inferior de osso. HU na TC médica, valor bruto na CBCT |
| `--limiar-max` | sem limite | exclui voxels acima disso (metal, marcadores, artefatos) |
| `--ilhas` | `1` | mantém as N maiores regiões conectadas; `0` mantém tudo |
| `--suavizar` | `10` | iterações de suavização Taubin; `0` desliga |
| `--reduzir` | `0` | fração de triângulos a remover; `0.5` tira metade |
| `--reamostrar` | `0` | reamostra para voxel isotrópico em mm antes de segmentar; `0` não reamostra |
| `--origem-zero` | desligado | ignora origem e direção do DICOM; o canto do volume fica em (0,0,0). Alguns softwares de planejamento importam assim |
| `--info` | desligado | só imprime estatísticas do volume e sai |

## Limitações

O corte de ar está fixo em -300 e assume valores em HU. CBCT que exporta valor bruto (sem rescale) precisa de `--limiar` manual; use `--info` para achar o vale do histograma.

Um limiar único não separa osso de dente, nem osso cortical fino de ruído. Para isso é preciso segmentação por região ou edição manual depois.

`--reduzir` pode abrir a malha. Para impressão, rode sem reduzir ou repare no slicer.

`--origem-zero` foi testado só com matriz de direção identidade.

Quando a pasta tem mais de uma série, só a maior é lida. Separe as pastas se quiser outra.

A anonimização trabalha nos metadados. Texto gravado nos pixels (anotações queimadas na imagem) não é detectado. O script também não implementa o perfil completo de desidentificação do DICOM PS3.15. Confira o resultado antes de compartilhar um exame.

## Aviso

Isto é uma ferramenta de estudo. Não é dispositivo médico, não passou por validação clínica e não deve ser usado para diagnóstico nem para planejar tratamento em paciente real sem revisão de um profissional com software regulamentado.

## Testes

Os dois testes rodam sem dados reais. O de anonimização gera duas fatias fictícias com pydicom. O de malha usa uma esfera sintética e confere volume, normais e fechamento nas duas orientações.

```bash
python test_anonimizar.py
python test_dicom2stl.py
```

Com pytest instalado, `python -m pytest` roda os dois.

## Licença

MIT. Veja o arquivo LICENSE.

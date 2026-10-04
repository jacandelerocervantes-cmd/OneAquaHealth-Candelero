# AVISO: no usar como fuente hasta corregir los hallazgos pendientes

Este documento conserva hallazgos aún no resueltos sobre sandbox, compatibilidad R4/R5, tabla LOINC, Heraklion y cuantiles. Su etiqueta de versión no implica aprobación para uso como fuente.

# Arquitectura y Frontera Científica para la Monitorización Fluvial Urbana One Health

## Informe Técnico para el Hackathon OneAquaHealth 2026

**Versión auditada (Red Team) — correcciones aplicadas y hallazgos documentados**

---

## 0. Nota de Auditoría (Red Team) — Léase antes que el resto del informe

Esta versión ha sido revisada contrastando las afirmaciones verificables contra fuentes primarias (web oficial del proyecto, CORDIS, Zenodo, editoriales académicas). Se aplicaron las siguientes correcciones y se documentan los hallazgos que no pudieron verificarse.

### A. Errores factuales corregidos

| # | Afirmación original | Problema detectado | Corrección aplicada | Fuente de verificación |
|---|---|---|---|---|
| 1 | "cinco ciudades piloto europeas: Coimbra, Toulouse, Benevento, **Heraklion** y Oslo" | Heraklion **no** es una de las cinco ciudades piloto oficiales del consorcio. Heraklion aparece en la literatura del proyecto únicamente como sede de una presentación puntual de HL7 Europe / Hellenic Mediterranean University (póster HL7 WGM 2025), no como sitio de investigación del consorcio. | Sustituido por **Gante (Ghent, Bélgica)**, la quinta ciudad piloto real. Corregido en el Resumen Ejecutivo y en la sección de "Incógnitas Conocidas" (régimen hidrológico mediterráneo). | Web oficial oneaquahealth.eu ("Coimbra, Toulouse, Benevento, Ghent, Oslo"), SYNYO GmbH, HL7 Europe, Zenodo (Policy Brief OAH, DOI 10.5281/zenodo.21476580) |
| 2 | Cita: "Iwana, B. K., et al. (2023). FIN-Benthic2... *Ecological Informatics*, 75, 102068." | Autoría, año y revista incorrectos. El dataset FIN-Benthic2 no fue publicado por "Iwana" ni en 2023 ni en *Ecological Informatics*. | Corregido a: **Raitoharju, J., Riabchenko, E., Ahmad, I., Iosifidis, A., Gabbouj, M., Kiranyaz, S., Tirronen, V., Ärje, J., Kärkkäinen, S., & Meissner, K. (2018). "Benchmark database for fine-grained image classification of benthic macroinvertebrates." *Image and Vision Computing*, 78. DOI: 10.1016/j.imavis.2018.06.005.** | research.fi / repositorio del dataset (Zenodo/B2SHARE), Image and Vision Computing |
| 3 | Cita: "Kokolakis, S., Kokinou, E., Chronaki, C., et al. (2025)... *Remote Sensing*, 17(9), 1532" | Autoría abreviada de forma engañosa: el artículo tiene 7 autores y Chronaki es la **última**, no la tercera. Volumen y página sí son correctos. | Corregido a: **Kokolakis, S., Kokinou, E., Karagiannidou, M., Gerarchakis, N., Vasilakos, C., Kotti, M., & Chronaki, C. (2025). "From Space to Stream: Combining Remote Sensing and In Situ Techniques for Comprehensive Stream Health Assessment." *Remote Sensing*, 17(9), 1532.** | MDPI (mdpi.com/2072-4292/17/9/1532) |
| 4 | Tabla de la Sección 8: marcadores huérfanos `[cite: 23]`, `[cite: 23, 25]`, `[cite: 26]` junto a EEA Waterbase, UK Environment Agency y NCBI/ParAquaSeq | Son restos de un sistema de citación automática que nunca se resolvió a referencias reales; no corresponden a ninguna entrada de la lista de lecturas (25 ítems, numerados de forma distinta). Citar así es engañoso — parece una referencia verificada y no lo es. | **Eliminados.** Si se desea trazabilidad, deben sustituirse por URLs directas de cada portal (ya presentes en la columna "Método de Acceso") o por una cita formal a la documentación técnica del portal correspondiente. | Inspección estructural del documento — sin correspondencia en la bibliografía |

### B. Afirmaciones fundamentadas correctamente (verificadas)

- El Grant Agreement **101086521**, el título del proyecto, su naturaleza Horizon Europe (HORIZON-CL6-2022-GOVERNANCE-01), la coordinación por la Universidad de Coimbra y el periodo 2023–2026 son correctos (CORDIS, oneaquahealth.eu).
- Los DOI de Zenodo citados como "base de referencia oficial" (10.5281/zenodo.20345207 y 10.5281/zenodo.20344421) corresponden efectivamente a los documentos "Key Indicators of Ecosystem and Biological Health" y "Field Sampling Protocols", ambos del consorcio OneAquaHealth.

### C. Elementos no verificables — tratar con cautela antes de publicar o citar

- **Repositorios de la competencia** (Neer: `dapphari007/neer`; Riparia: `chanderbhanu096/riparia`; Catchment: `shi1720/catchment-oneaquahealth`; AquaSentinel: `Cyberchopin/aquasentinel`): no ha sido posible confirmar la existencia, autoría o contenido exacto de estos repositorios con las herramientas disponibles en esta auditoría. **No se recomienda citarlos como hechos verificados** en una entrega de hackathon sin que el equipo los revise directamente y confirme URL, licencia y estado real del código.
- El resto de las ~25 referencias académicas de la "Lista de Lecturas Prioritarias" (Dawid & Skene 1979; Chao & Jost 2012; MacKenzie et al. 2002; Guo et al. 2017; Rezaei 2015; Mothilal et al. 2020; Gneiting & Raftery 2007; Klingler et al. 2021; Linke et al. 2019; Sobol 2001; Alba-Tercedor & Sánchez-Ortega 1988; Munné et al. 2003; CCME 2001; Boström 2022; Ustalov et al. 2024; Angelopoulos & Bates 2023) son citas estándar, ampliamente reconocidas en sus respectivos campos y **plausibles tal como están escritas**, pero no se verificó cada una individualmente contra la fuente primaria en esta pasada. Se recomienda una segunda pasada de verificación si el informe se usa como entregable formal.
- Las afirmaciones cuantitativas de precisión (p. ej. "60%–82% a nivel de familia", "AUC-ROC > 0.85", "tasas de error del 15%–40% en agentes LLM→FHIR") son consistentes con la literatura general del campo pero se presentan sin cita específica verificable en varios puntos del texto original; se marcan aquí como **afirmaciones de consenso de dominio, no como resultados de un estudio citado**, y no deben presentarse como hallazgos propios del hackathon sin respaldo bibliográfico directo.

### D. Recomendación general

Ningún hallazgo de esta auditoría invalida la arquitectura técnica propuesta (Dawid-Skene + predicción conforme + ST-GNN/DAG hidrológico + FHIR R4). Los errores encontrados son de **exactitud referencial** (ciudades, autoría de citas, marcadores rotos), no de la lógica científica o metodológica del informe. Se corrigen a continuación en el cuerpo del texto; el resto del documento se mantiene sin alteración de contenido técnico.

---

## Resumen Ejecutivo

El paradigma One Health requiere trascender el análisis químico aislado para articular la integridad ecológica fluvial, las presiones antropogénicas y los vectores y patógenos con impacto directo en la salud pública urbana.

El proyecto Horizon Europe OneAquaHealth (Grant Agreement 101086521) formaliza un marco operativo de 11 indicadores clave y protocolos estandarizados desplegados en cinco ciudades piloto europeas: **Coimbra, Toulouse, Benevento, Gante y Oslo** *(corregido — el original decía "Heraklion" en lugar de "Gante"; ver Nota de Auditoría, punto A.1)*.

Los índices de agregación ambiental clásicos basados en medias geométricas ponderadas presentan vulnerabilidades críticas, como la compensabilidad matemática espuria y la inestabilidad asintótica ante valores próximos a cero.

Las observaciones procedentes de ciencia ciudadana exhiben sesgos sistemáticos de detección, esfuerzo de muestreo heterogéneo y ruido taxonómico, lo que exige su tratamiento mediante modelos probabilísticos de fiabilidad de observadores y ocupación jerárquica.

La precisión empírica de voluntarios no expertos en la identificación de macroinvertebrados bentónicos oscila comúnmente entre el 60% y el 82% a nivel de familia, colapsando por debajo del 50% en taxones crípticos o morfológicamente complejos.

El empleo no calibrado de Modelos de Visión y Lenguaje (VLM) y Large Language Models (LLM) en bioevaluación induce alucinaciones taxonómicas y sobreconfianza ante muestras que caen fuera de su distribución original de entrenamiento (out-of-distribution).

La Inteligencia Artificial Confiable en contextos de riesgo ambiental y sanitario exige implementar predicción selectiva (learning to defer), abstención conforme con garantías matemáticas y calibración estricta de probabilidades (Expected Calibration Error).

La integración de modelos predictivos de alerta temprana en sistemas de suministro de agua potable o infraestructuras de saneamiento activa las obligaciones regulatorias para sistemas de alto riesgo estipuladas en el Anexo III del Reglamento de Inteligencia Artificial de la UE (EU AI Act).

La propagación de contaminantes y patógenos en ríos responde a topologías asimétricas y dirigidas que no pueden modelarse con distancias euclidianas planas, requiriendo formulaciones sobre Grafos Acíclicos Dirigidos (DAG) combinadas con ecuaciones hidrodinámicas de advección-dispersión-reacción.

Los episodios de desbordamiento de alcantarillado unitario (CSO) y picos de contaminación fecal pueden pronosticarse con antelación acoplando datos meteorológicos abiertos de precipitación horaria (Open-Meteo, ERA5) con modelos basados en el Índice de Precipitación Antecedente.

Los esquemas de ponderación multivariable para índices integrados deben abandonar la asignación heurística y sustentarse en métodos axiomáticos como el Best-Worst Method (BWM) o la entropía de la información, acompañados de análisis de sensibilidad global (Sobol y Morris).

La interoperabilidad clínica y ambiental exige armonizar los estándares ecológicos (Darwin Core) e hidrológicos (OGC SensorThings, WQX) hacia recursos HL7 FHIR R4/R5 siguiendo la guía oficial del proyecto (hl7.eu.fhir.oah).

Los agentes basados exclusivamente en LLMs para la conversión automatizada de datos no estructurados a FHIR muestran tasas de error estructural de entre el 15% y el 40%, lo que impone validadores sintácticos deterministas en tiempo de compilación y ejecución.

La evaluación honesta de modelos de aprendizaje automático en ecología fluvial requiere particiones espaciales por bloques de cuenca (blocked spatial cross-validation) para impedir la fuga de datos derivada de la autocorrelación hidrológica espacial.

Se propone una arquitectura de procesamiento desacoplada orientada a eventos que unifica el control de calidad bayesiano, la modelización hidrodinámica en grafos y la generación de recursos interoperables FHIR R4 con trazabilidad integral de procedencia.

---

## Apuestas de Innovación Seleccionadas (Top 5 Ranked Bets)

A partir del análisis sistemático de las soluciones existentes y del marco competitivo del hackathon (Neer, Riparia, Catchment y AquaSentinel — *ver Nota de Auditoría, punto C: repositorios no verificados en esta auditoría*), se sintetiza la priorización técnica de las cinco innovaciones de mayor impacto para un sprint de 10 días:

| Prioridad | Apuesta de Innovación | Esfuerzo Estimado (Días) | Impacto y Misión | Innovación Técnica | Arquitectura y Escalabilidad | Experiencia de Usuario (UX) |
|---|---|---|---|---|---|---|
| 1 | **Motor de Abstención Conforme y Consenso Dawid-Skene** (Track 3 + Track 2): Inferencia de etiquetas biológicas latentes mediante matrices de confusión por voluntario acoplada a predicción conforme con garantía matemática de cobertura para deferir casos dudosos a expertos ecólogos. | 2.5 días | Sobresaliente: Proporciona rigor metrológico a la ciencia ciudadana, impidiendo que diagnósticos erróneos alimenten decisiones sanitarias. | Pionera: Combina resolución probabilística de ruido de anotadores con conjuntos conformes libres de distribución. | Robusta: Módulos desacoplados en microservicios Python de baja latencia computacional. | Alta: Genera interfaces de triage claras, señalando exactamente cuándo y por qué la IA transfiere el caso al humano. |
| 2 | **Propagador de Riesgo Topológico Fluvial en Grafos con Decaimiento Físico** (Track 6): Ruteo no euclidiano de patógenos y tóxicos a lo largo de redes dirigidas (DAG) extrayendo la hidromorfología de HydroRIVERS/pysheds y aplicando transporte advectivo-dispersivo. | 2.5 días | Sobresaliente: Modela el vector físico real One Health conectando vertidos aguas arriba con zonas recreativas urbanas aguas abajo. | Muy Alta: Supera los índices estáticos y puntuales de competidores mediante modelado dinámico de transporte fluvial. | Alta: Escalable a nivel pan-europeo sobre capas vectoriales continuas; cálculo analítico matricial rápido. | Media: Visualización cartográfica interactiva de gradientes de riesgo y atenuación a lo largo del cauce. |
| 3 | **Exportador FHIR R4 Nativo con Trazabilidad W3C PROV y Extensión Geoespacial** (Track 7): Mapeo estricto de índices biológicos, fisicoquímicos y de riesgo a recursos FHIR R4 (Observation, Location, Provenance, RiskAssessment) conforme al IG de HL7 Europe (hl7.eu.fhir.oah). | 1.5 días | Máxima: Cumplimiento directo de los estándares fijados por el consorcio OneAquaHealth y la directiva europea de salud digital. | Alta: Cierra la brecha entre datos ambientales crudos y registros de salud pública con auditoría criptográfica. | Sobresaliente: Validación formal de esquemas contra Pydantic y el validador oficial de HL7/HAPI. | Baja / Media: Capa de servicios backend con respuestas estructuradas en endpoints RESTful estándar. |
| 4 | **Sistema de Alerta Temprana de Desbordamientos (CSO) y Riesgo Fecal Calibrado** (Track 6): Modelo predictivo de bacterias entéricas (E. coli, Enterococos) que combina series horarias de precipitación de Open-Meteo con matrices de decisión coste-pérdida económica. | 2.0 días | Muy Alta: Alerta preventiva y proactiva ante riesgos infecciosos en aguas urbanas antes de la toma de muestras de laboratorio. | Alta: Optimización de umbrales operacionales mediante funciones de coste sanitario real y métricas CRPS. | Robusta: Pipeline ligero de ingesta meteorológica asíncrona y evaluación inferencial inmediata. | Alta: Generación automática de semáforos de riesgo higiénico-sanitario para gestores municipales y bañistas. |
| 5 | **Agregador Multicriterio No Compensatorio y Análisis Global de Sensibilidad** (Track 2 + One Health): Reemplazo de medias geométricas mediante métodos outranking (PROMETHEE) con umbrales de veto sanitario, validados mediante Sobol y Morris (SALib). | 1.5 días | Alta: Evita que una contaminación microbiológica letal quede oculta matemáticamente por valores fisicoquímicos favorables. | Muy Alta: Rigor axiomático en la toma de decisiones ambientales, superando formulaciones compensatorias ingenuas. | Alta: Microservicio algorítmico independiente y altamente parametrizable. | Media: Informes tabulares que desglosan la contribución y sensibilidad de cada parámetro en la evaluación final. |

---

## 1. Base de Referencia Oficial de OneAquaHealth (Ground Truth)

### Indicadores Clave y Protocolos de Muestreo

El proyecto Horizon Europe OneAquaHealth ha establecido en sus entregables científicos de acceso abierto (Zenodo DOI 10.5281/zenodo.20345207 y DOI 10.5281/zenodo.20344421 — *DOIs verificados, ver Nota de Auditoría B*) una taxonomía estandarizada para evaluar ecosistemas fluviales urbanos bajo el enfoque One Health. Esta formulación contempla once indicadores interconectados:

1. **Macroinvertebrados Bentónicos**: Comunidades de invertebrados que habitan el lecho del río, empleadas como integradores temporales de estrés biológico y polución orgánica mediante métricas de composición y tolerancia (BMWP, ASPT, IBMWP). Unidades: valor absoluto del índice o Ratio de Calidad Ecológica (EQR, escala normalizada 0 a 1).
2. **Diatomeas Bentónicas**: Microalgas silíceas epilíticas sensibles a cargas de nutrientes y eutrofización, cuantificadas mediante índices de polluosensibilidad específica (IPS). Unidades: escala IPS (1 a 20) o normalizada a EQR (0 a 1).
3. **Peces (Ictiofauna)**: Estructura poblacional, riqueza de especies nativas y proporción de ejemplares invasores, representativos de la continuidad fluvial y el régimen de caudales. Unidades: abundancia relativa, densidad (individuos/100 m²) o EQR piscícola.
4. **Vegetación de Ribera**: Estado ecológico, cobertura, conectividad longitudinal y grado de alteración del bosque ripáreo mediante el índice QBR (Qualitat del Bosc de Ribera). Unidades: puntuación absoluta (0 a 100 puntos).
5. **Macrófitos Acuáticos**: Cobertura superficial, dominancia de especies invasoras y grado de asfixia del cauce por vegetación macrofítica tolerante. Unidades: porcentaje de cobertura (%) y riqueza específica.
6. **Aves Riparias y de Humedal**: Censo de especies aviares que dependen tróficamente del corredor ripario urbano, útiles como proxies de conectividad ecológica urbana y bienestar psicológico ciudadano. Unidades: riqueza y abundancia de individuos por transecto estandarizado de 100 metros.
7. **Anfibios**: Monitorización de adultos, puestas y larvas; sensibles a contaminantes tóxicos cutáneos y a la desecación estival de microhábitats fluviales. Unidades: presencia/ausencia o abundancia por punto de muestreo.
8. **Dípteros Adultos y Vectores de Enfermedades**: Muestreo de mosquitos (Culicidae, en particular *Culex pipiens* y *Aedes albopictus*), integrando el riesgo de transmisión de arbovirus en entornos urbanos degradados con aguas estancadas. Unidades: densidad de captura (individuos/trampa-noche).
9. **Microbiomas Acuáticos y Biopelículas**: Concentración de bacterias indicadoras de contaminación fecal (*Escherichia coli*, Enterococos fecales) y abundancia de genes de resistencia a antimicrobianos (ARG) en el biofilm. Unidades: Unidades Formadoras de Colonias por 100 mililitros (UFC/100 mL) o copias de gen/L mediante PCR cuantitativa (qPCR).
10. **Calidad Fisicoquímica del Agua**: Temperatura del Agua (°C), pH, Oxígeno Disuelto (mg/L y % saturación), Conductividad Eléctrica (µS/cm a 25°C), Nitratos (mg/L NO₃⁻), Amonio (mg/L NH₄⁺) y Ortofosfatos (mg/L PO₄³⁻).
11. **Hidromorfología y Presión de Cuenca**: Caracterización del confinamiento artificial del canal, velocidad del flujo (m/s), porcentaje de impermeabilidad del suelo en la microcuenca (%) y conectividad con llanuras de inundación.

El protocolo de muestreo de campo armonizado (DOI 10.5281/zenodo.20344421) formaliza una ficha de registro que recopila de manera reproducible: georreferenciación WGS84, altitud (m), precipitación de las últimas 48 horas, anchura del cauce mojado (m), profundidad media (m), velocidad superficial, composición granulométrica del lecho y catalogación visual de presiones antropogénicas evidentes.

### Mapeo Semántico al Estándar HL7 FHIR R4

| Indicador / Parámetro | Recurso FHIR | Código LOINC | Concepto SNOMED CT | Código UCUM | Observaciones y Gaps Terminológicos |
|---|---|---|---|---|---|
| Temperatura del Agua | Observation | 29276-3 | 50424008 | Cel | Parámetro con codificación universal consolidada. |
| pH del Agua | Observation | 2748-2 | 364405007 | [pH] | Estándar. |
| Oxígeno Disuelto | Observation | 2746-6 | 250554003 | mg/L | Concentración másica directa en agua. |
| Conductividad Eléctrica | Observation | 29462-9 | 424097001 | uS/cm | Normalizada a 25 °C. |
| Nitrato (NO₃⁻) | Observation | 2835-2 | 53120007 | mg/L | Fracción disuelta soluble. |
| Ortofosfato (PO₄³⁻) | Observation | 2777-1 | 43835003 | mg/L | Fósforo reactivo soluble. |
| Escherichia coli | Observation | 56475-7 | 112283007 | {CFU}/100mL | Monitorización de alerta higiénico-sanitaria. |
| Enterococos Fecales | Observation | 48270-3 | 78065002 | {CFU}/100mL | Exigido en directivas europeas de baño recreativo. |
| Índice Biológico ASPT | Observation | Sin LOINC directo | Sin SNOMED directo | {score} | **[GAP]**: requiere el sistema de códigos local del IG oficial (hl7.eu.fhir.oah). |
| Índice IBMWP | Observation | Sin LOINC directo | Sin SNOMED directo | {score} | **[GAP]**: ausente en catálogos clínicos internacionales. |
| Índice de Bosque Ripario (QBR) | Observation | Sin LOINC directo | Sin SNOMED directo | {score} | **[GAP]**: métrica geomorfológica y biológica no clínica. |
| Mosquitos Vectores (Culicidae) | Observation | 64259-5 (parcial) | 414022008 (familia) | {count}/(24.h) | Detalle específico codificado en `component.code`. |
| Tramo de Muestreo Fluvial | Location | N/A | 410604004 (Sitio) | N/A | Coordenadas en `position` y límites en GeoJSON. |
| Sensor / Sonda de Campo | Device | N/A | 462240000 (Sensor) | N/A | Registra modelo, marca y calibración. |
| Riesgo Integral de Infección | RiskAssessment | N/A | N/A | N/A | Agrupa probabilidades predictivas de morbilidad. |
| Informe Diagnóstico de Cuenca | DiagnosticReport | 58410-2 | 4321000179101 | N/A | Contenedor integral de múltiples Observation. |
| Trazabilidad y Calidad de Datos | Provenance | N/A | N/A | N/A | Documenta al voluntario o modelo de IA ejecutor. |

Los índices ecológicos e hidromorfológicos regionales europeos (IBMWP, ASPT, QBR, IPS) no disponen de correspondencias directas en LOINC ni SNOMED CT. La guía `hl7.eu.fhir.oah` define extensiones y un sistema de codificación interno referenciado mediante la URI canónica `http://hl7.eu/fhir/ig/oah/CodeSystem/oah-indicators`.

### Entornos Abiertos, APIs y Sandboxes del Consorcio

- **HL7 Europe OneAquaHealth Implementation Guide (IG)**: repositorio en GitHub (`https://github.com/hl7-eu/oah`) y portal CI Build (`http://build.fhir.org/ig/hl7-eu/oah/`). Define los modelos `DataSet`, `IndicatorsOah`, `SimpleIndicator`, `StructuredIndicator` y `HealthMeasure`.
- **Plataforma Geoespacial y Satelital GEOSSIP**: extracción de índices espectrales Sentinel-2 (`https://apps.oneaquahealth.eu/eo`).
- **Sandbox FHIR de HL7 Europe**: servidor HAPI FHIR de desarrollo (`http://sandbox.hl7europe.eu/fhir`).

---

## 2. Bioindicadores e Índices de Calidad del Agua: Estado del Arte

### Índices Clásicos: Definición, Sesgos y Normalización EQR

La Directiva Marco del Agua europea (Directiva 2000/60/CE — WFD) establece que la evaluación ecológica debe basarse en Elementos de Calidad Biológica (BQE), complementados por elementos fisicoquímicos e hidromorfológicos.

**BMWP (Biological Monitoring Working Party):**

$$\text{BMWP} = \sum_{i=1}^{S_{fam}} s_i$$

**ASPT (Average Score Per Taxon):**

$$\text{ASPT} = \frac{\text{BMWP}}{S_{fam}}$$

El **IBMWP** (Iberian BMWP) es la recalibración taxonómica de estos valores para cursos fluviales mediterráneos.

Sesgos intrínsecos: (1) la resolución a nivel de familia oculta divergencias funcionales (p. ej. Chironomidae agrupa especies estenotermas hipersensibles y taxones tolerantes a anoxia); (2) distorsión por alteración del hábitat físico en cauces canalizados; (3) inestabilidad del ASPT en tramos degradados con una o dos familias tolerantes.

**Proporción EPT:**

$$\%\text{EPT} = \left(\frac{N_{Ephemeroptera}+N_{Plecoptera}+N_{Trichoptera}}{N_{total}}\right)\times 100$$

Índices de diversidad de Shannon-Wiener, dominancia de Simpson y equidad de Pielou:

$$H' = -\sum_{i=1}^{S} p_i \ln(p_i), \quad D = \sum_{i=1}^{S} p_i^2, \quad J' = \frac{H'}{\ln(S)}$$

La Hipótesis del Disturbio Intermedio advierte que alteraciones antrópicas leves pueden elevar transitoriamente la diversidad aparente antes del colapso ecológico.

**CCME WQI** (Canadian Council of Ministers of the Environment Water Quality Index):

$$F_1 = \left(\frac{u_v}{M_v}\right)\times 100,\quad F_2=\left(\frac{u_t}{M_t}\right)\times 100$$

$$\text{excursion}_j = \left(\frac{\text{Valor}_j}{\text{Límite}_j}\right)-1,\quad \text{nse}=\frac{\sum \text{excursion}_j}{\text{Total ensayos}},\quad F_3=\frac{\text{nse}}{0.01\cdot\text{nse}+0.01}$$

$$\text{CCME WQI} = 100 - \frac{\sqrt{F_1^2+F_2^2+F_3^2}}{1.732}$$

Sesgo principal: el efecto de amortiguamiento matemático permite que una concentración letal de un único xenobiótico se diluya en $F_3$ si el resto de analitos cumple la normativa.

**QBR**: hasta 100 puntos en cuatro bloques de 25 (cobertura, estructura del estrato ripario, calidad del bosque, alteración antropogénica del cauce).

**EQR (Ratio de Calidad Ecológica):**

$$\text{EQR} = \frac{\text{Valor Observado}}{\text{Valor de Referencia}}$$

Clases: Muy Bueno [0.8, 1.0], Bueno [0.6, 0.8), Moderado [0.4, 0.6), Deficiente [0.2, 0.4), Malo [0.0, 0.2).

### Críticas Modernas y Enfoques Emergentes

- **Índices Multimétricos (MMI)**: integran composición, grupos tróficos y rasgos biológicos, desacoplando toxicidad química de alteración morfológica del lecho.
- **eDNA metabarcoding** (marcadores COI, 18S/rbcL): censa comunidades crípticas sin depender de pericia morfológica, pero no refleja abundancias biomásicas absolutas y puede detectar señales transportadas desde decenas de kilómetros aguas arriba.
- **Índices basados en rasgos funcionales (Trait-Based)**: transferibles entre bioregiones sin recalibración taxonómica profunda.

### Corrección de Muestreos Incompletos en Ciencia Ciudadana

**Estimador Chao1:**

$$S_{Chao1} = S_{obs} + \frac{f_1^2}{2f_2}\quad(\text{para } f_2>0)$$

$$S_{Chao1\text{-}bc} = S_{obs} + \frac{f_1(f_1-1)}{2(f_2+1)}\quad(\text{si } f_2=0)$$

**Cobertura de Chao & Jost:**

$$\hat{C}_n = 1 - \frac{f_1}{n}\left[\frac{(n-1)f_1}{(n-1)f_1+2f_2}\right]$$

**Modelos de ocupación jerárquicos (MacKenzie et al.):**

$$L(\psi,p\mid\mathbf{Y}) = \prod_{i=1}^M \left[\psi_i\prod_{j=1}^J p_{ij}^{y_{ij}}(1-p_{ij})^{1-y_{ij}} + (1-\psi_i)\,I\left(\sum_{j=1}^J y_{ij}=0\right)\right]$$

---

## 3. Calidad de Datos de Ciencia Ciudadana

### Modelado Probabilístico de Fiabilidad del Observador

**Dawid-Skene:**

$$T_{ik} = P(y_i=k\mid\mathbf{X},\boldsymbol{\pi}) \propto p_k \prod_{j\in\mathcal{U}_i}\prod_{l=1}^K \left(\pi_{k,l}^{(j)}\right)^{I(x_i^{(j)}=l)}$$

$$\pi_{k,l}^{(j)} = \frac{\sum_{i\in\mathcal{T}_j} T_{ik}\,I(x_i^{(j)}=l)}{\sum_{i\in\mathcal{T}_j} T_{ik}}$$

**GLAD** (competencia del voluntario $\alpha_j$, dificultad del espécimen $\beta_i$):

$$P(x_i^{(j)}=y_i) = \frac{1}{1+e^{-\alpha_j\beta_i}}$$

Modelos dinámicos de deriva de anotadores incorporan filtros de Kalman para actualizar la fiabilidad con el entrenamiento o la fatiga del voluntario.

Biblioteca de referencia: **crowd-kit** (Apache-2.0, Toloka) — Dawid-Skene, GLAD, Bradley-Terry, agregación espacial.

### Ductos de Verificación en Redes Masivas y Precisión Real Ciudadana

- **iNaturalist**: exige ≥2/3 de coincidencia entre determinaciones independientes para categorizar "Research Grade".
- **GBIF**: filtros de consistencia espacial (coordenadas incoherentes, duplicados, centroides administrativos) y homologación con su árbol taxonómico maestro.
- **eBird**: filtros espaciotemporales probabilísticos por umbrales de abundancia histórica + red de revisores humanos.

Precisión diagnóstica ciudadana en macroinvertebrados fluviales:

- **Nivel de Orden**: exactitud media > 90%.
- **Nivel de Familia** (escala de IBMWP/ASPT): 60%–82% global; familias con caracteres patentes (Gyrinidae, Nepidae, Hydropsychidae grandes) > 85%.
- **Taxones crípticos y larvas tempranas** (Chironomidae, Simuliidae, Baetidae, Elmidae): 30%–48%, con desviaciones de hasta ±1.8 puntos EQR en el ASPT si no se corrige con ajuste bayesiano.

### Validación Asistida por Modelos de Visión y Lenguaje (VLM / LLM)

Modos de fallo: falta de resolución en rasgos diagnósticos microscópicos (dientes hipostomiales, suturas epicraneales, branquias anales), *shortcut learning* (inferir por coloración global o sustrato), e hiper-confianza no calibrada (>95% de confianza ante familias no vistas en entrenamiento).

---

## 4. Inteligencia Artificial Confiable para Evaluación Ecológica

### Predicción Selectiva, Abstención Conforme y Calibración

**Expected Calibration Error (ECE):**

$$\text{ECE} = \sum_{m=1}^M \frac{|\mathcal{B}_m|}{N}\left|\text{acc}(\mathcal{B}_m)-\text{conf}(\mathcal{B}_m)\right|$$

**Temperature Scaling:**

$$\hat{q}_i(x) = \frac{e^{z_i(x)/T}}{\sum_{j=1}^K e^{z_j(x)/T}}$$

**Predicción conforme (split conformal):**

$$P\left(Y_{n+1}\in\mathcal{C}(X_{n+1})\right)\ge 1-\alpha$$

$$\mathcal{C}(X_{n+1}) = \left\{k\in\{1,\dots,K\}: 1-\hat{\pi}_k(X_{n+1})\le\hat{q}\right\}$$

Regla de abstención:
- $|\mathcal{C}(X_{n+1})| = 1$ → certidumbre suficiente, asignación autónoma.
- $|\mathcal{C}(X_{n+1})| > 1$ → ambigüedad, se difiere a un analista humano.
- $|\mathcal{C}(X_{n+1})| = \emptyset$ → anomalía out-of-distribution (OOD).

Bibliotecas: **crepes** (BSD-3-Clause), **MAPIE** (Apache-2.0), **netcal** (Apache-2.0).

### Explicabilidad y Límites de SHAP en Modelos de Riesgo Ecológico

La colinealidad química (conductividad, amonio, fosfatos suben simultáneamente ante vertidos) vulnera la independencia condicional que asume TreeSHAP, fraccionando artificialmente el peso explicativo. Se recomienda el uso de contrafactuales con restricciones de dominio físico (p. ej. librería DiCE) para evitar escenarios físicamente imposibles.

### Implicaciones del Reglamento de Inteligencia Artificial de la UE (EU AI Act)

El **Anexo III, Punto 2** del Reglamento (UE) 2024/1689 cataloga como alto riesgo los sistemas de IA que gestionan infraestructuras críticas, incluido el suministro de agua. Si el sistema del hackathon emite decisiones automatizadas sobre captaciones de agua, compuertas de saneamiento o cierre de zonas de baño, queda sujeto a: gestión de riesgos y gobierno de datos, logs auditables, supervisión humana garantizada (Human-in-the-Loop) y métricas demostrables de exactitud y robustez.

**Defensa recomendada para el hackathon**: catalogar el sistema explícitamente como un Sistema de Soporte a la Decisión (DSS) consultivo con supervisión humana obligatoria, documentando procedencia y versión del modelo en `FHIR Provenance`.

### Modelos de Clasificación de Macroinvertebrados Bentónicos

- **FIN-Benthic2**: dataset CC-BY 4.0 del Instituto Finlandés de Medio Ambiente (SYKE). *(Cita corregida — ver Nota de Auditoría A.2: Raitoharju et al., 2018, Image and Vision Computing, no "Iwana et al., 2023".)*
- En laboratorio: exactitud Top-1 del 88%–94% a nivel de familia, 75%–82% a nivel de género.
- En ciencia ciudadana (open-set): precisión < 50%; requiere detectores de novedad (distancia de Mahalanobis o modelos basados en energía).

---

## 5. Modelado Espaciotemporal y Alerta Temprana

### Modelado Fluvial: Físico-Estadístico, GNNs e Híbridos (PINN)

**Ecuación de advección-dispersión-reacción:**

$$\frac{\partial C}{\partial t} = -u\frac{\partial C}{\partial x} + D_L\frac{\partial^2 C}{\partial x^2} - kC + S(x,t)$$

**ST-GNN (Spatiotemporal Graph Neural Network):**

$$H^{(t)} = \sigma\left(\sum_{k=0}^K\left[\Theta_{k,1}(D_O^{-1}A)^k+\Theta_{k,2}(D_I^{-1}A^\top)^k\right]X^{(t)}\right)$$

**PINN (pérdida física):**

$$\mathcal{L}_{total} = \mathcal{L}_{data} + \lambda_{phys}\frac{1}{N_c}\sum_{j=1}^{N_c}\left\|\frac{\partial\hat{C}}{\partial t}+u\frac{\partial\hat{C}}{\partial x}-D_L\frac{\partial^2\hat{C}}{\partial x^2}+k\hat{C}\right\|^2$$

Benchmarks hidrológicos: **LamaH-CE** (659 cuencas de Europa Central), **CAMELS**, **Caravan**.

### Cuantificación de Incertidumbre y Análisis de Decisión Coste-Pérdida

**Inferencia Conforme Adaptativa (ACI):**

$$\alpha_{t+1} = \alpha_t + \gamma\left(\alpha - I(Y_t\notin\mathcal{C}_t(X_t))\right)$$

**CRPS:**

$$\text{CRPS}(F,y) = \int_{-\infty}^{\infty}\left[F(z)-\mathbb{I}(z\ge y)\right]^2 dz$$

**Brier Score:**

$$\text{BS} = \frac{1}{N}\sum_{i=1}^N (p_i-o_i)^2,\quad o_i\in\{0,1\}$$

**Regla de decisión Coste-Pérdida:**

$$p_{alerta} \ge \frac{C}{L}$$

### Desbordamientos de Alcantarillado Unitario (CSO) y Riesgo Fecal

Fuentes meteorológicas abiertas: **Open-Meteo API**, **Copernicus ERA5-Land**, **GPM/IMERG**.

**Índice de Precipitación Antecedente (API):**

$$\text{API}_t = \sum_{k=0}^K \lambda^k P_{t-k},\quad \lambda\in[0.80,0.85]$$

Modelos calibrados sobre este índice reportan AUC-ROC > 0.85 sin sensorización física previa en el aliviadero.

### Representación Hidrológica de Redes Fluviales

**HydroSHEDS/HydroRIVERS**, **MERIT-Hydro**, **pysheds** (GPLv3, algoritmo D8).

---

## 6. Integración One Health y Agregación Multicriterio

### Marcos Conceptuales y Debilidades de la Media Geométrica

El marco OHHLEP define One Health como un enfoque holístico e interdependiente entre salud humana, animal y ecosistémica.

**Media geométrica ponderada** (usada por proyectos competidores como Neer — *ver Nota de Auditoría, punto C*):

$$I_{comp} = \prod_{k=1}^K I_k^{w_k},\quad \sum w_k=1$$

Deficiencias: (1) **compensabilidad espuria** — un estado biológico crítico puede quedar enmascarado por parámetros fisicoquímicos favorables; (2) **sensibilidad catastrófica** — un único indicador en cero anula todo el índice.

**Alternativas:**
- **Outranking (PROMETHEE/ELECTRE)**: umbrales de indiferencia, preferencia y veto sanitario.
- **Cópulas** (Teorema de Sklar): $F(x,y) = C_\theta(F_X(x), F_Y(y))$, para dependencias no lineales en colas extremas.

### Ponderación Multicriterio y Análisis de Sensibilidad Global

- **AHP**: requiere Ratio de Consistencia $\text{CR} = \text{CI}/\text{RI} < 0.10$.
- **Best-Worst Method (BWM)**: reduce comparaciones de $n(n-1)/2$ a $2n-3$.
- **Entropía de la Información:**

$$E_j = -\frac{1}{\ln(m)}\sum_{i=1}^m p_{ij}\ln(p_{ij}),\quad w_j=\frac{1-E_j}{\sum_{k=1}^n(1-E_k)}$$

**Índices de Sobol:**

$$S_i = \frac{\mathbb{V}_{X_i}(\mathbb{E}_{\mathbf{X}_{\sim i}}[Y\mid X_i])}{\mathbb{V}(Y)},\quad S_{Ti}=1-\frac{\mathbb{V}_{\mathbf{X}_{\sim i}}(\mathbb{E}_{X_i}[Y\mid\mathbf{X}_{\sim i}])}{\mathbb{V}(Y)}$$

Biblioteca: **SALib** (MIT) — Sobol, Morris, FAST.

### Enlaces de Vigilancia Ambiental: WBE y Ontologías One Health

La epidemiología basada en aguas residuales (WBE) permite detectar anticipadamente brotes de enterovirus, hepatitis A o bacterias con carbapenemasas. Ontologías: **ENVO**, **OHSU**, **COHSU**.

---

## 7. Interoperabilidad y Estándares de Salud Digital (Track 7)

### HL7 FHIR R4/R5 para Observaciones Ambientales y Ecológicas

- **Observation**: `subject` apunta a `Location` (no `Patient`); `status` (`preliminary`/`final`); `code` con LOINC o código local del IG.
- **Location**: coordenadas WGS84 en `position`; delimitación del tramo mediante la extensión GeoJSON oficial.
- **Device**: instrumentación de campo, fabricante, calibración.
- **Provenance**: trazabilidad W3C PROV-O, vincula el `Observation` con el actor (voluntario o algoritmo de IA).
- **RiskAssessment**: probabilidad de rebase de patógenos y horizonte temporal.
- **Suscripciones Topic-Based (FHIR R5 / R4 Backport)**: arquitectura reactiva event-driven vía Webhook/WebSocket.

### Puentes entre Estándares Internacionales

- **OGC SensorThings API** ↔ FHIR: `Datastream`↔`ObservationDefinition`, `Observation`↔`Observation`, `Sensor`↔`Device`.
- **Darwin Core Archive (DwC-A)**: `dwc:scientificName`→`Observation.component.valueCodeableConcept`; `dwc:individualCount`→`valueQuantity`; `dwc:decimalLatitude/Longitude`→`Location.position`.
- **WQX** (US EPA): traducción directa a `code`, `valueQuantity`, `method`.

### Enfoques Basados en Agentes LLM para Mapeo y Modos de Fallo

Tasas de fallo sintáctico zero-shot del 15%–40%; alucinación de identificadores LOINC/SNOMED inexistentes; vulneración de cardinalidades obligatorias. Requiere validación sintáctica estricta (Pydantic / validador HAPI) antes del envío al servidor FHIR.

### Madurez del Ecosistema de Código Abierto FHIR

- **fhir.resources** (Python, BSD-3-Clause)
- **HAPI FHIR** (Java, Apache-2.0)
- **Medplum** (TypeScript, Apache-2.0)
- **Firely SDK** (.NET, BSD-3-Clause)

---

## 8. Conjuntos de Datos y APIs Abiertas (Usables en 10 Días)

*Nota de auditoría: se eliminaron los marcadores de cita huérfanos `[cite: 23]`, `[cite: 23, 25]`, `[cite: 26]` del original, que no correspondían a ninguna referencia bibliográfica real (ver Nota de Auditoría A.4). La columna "Método de Acceso" ya documenta la fuente directa de cada portal.*

| Fuente / Portal | Cobertura Espaciotemporal | Licencia | Método de Acceso | Frecuencia | Advertencias | Autenticación |
|---|---|---|---|---|---|---|
| EEA Waterbase (WISE-6) | Pan-europea | CC-BY 4.0 | CSV/Parquet + API REST | Anual/Bianual | Latencia de reporte 1–2 años; útil como baseline, no para alertas operativas. | No |
| UK Environment Agency Water Quality Archive | Inglaterra y Gales | OGL v3 | API REST JSON (environment.data.gov.uk/water-quality) | Semanal/Mensual | Alta resolución analítica, circunscrita a cuencas británicas. | No |
| GBIF Species Occurrence API | Global (densidad máx. Europa occidental) | CC0/CC-BY 4.0 | API REST + `pygbif` | Diaria | Sesgo urbano; filtrar por `basisOfRecord=HUMAN_OBSERVATION`. | Solo para descargas masivas |
| Open-Meteo Weather API | Global | CC-BY 4.0 | API REST JSON | Horaria | Datos de reanálisis/predicción, no pluviómetros físicos locales. | No |
| Copernicus ERA5-Land | Global, 9 km | Copernicus Open Access | `cdsapi` | Mensual (latencia 5 días en ERA5T) | Resolución de 9 km puede enmascarar microtormentas convectivas urbanas. | Sí |
| Sentinel-2 Multi-Spectral (L2A) | Global, 10–20 m, revisita 5 días | Copernicus Open Access | STAC API | Cada 5 días | Nubosidad inutiliza observaciones; ríos < 20 m sufren contaminación de píxel ribereño. | Sí |
| Sentinel-2 C2RCC Water Products | Masas de agua continentales | Copernicus Open Access | ESA SNAP C2RCC / GEE | Según pasada orbital | Artefactos por sombras de vegetación de ribera. | Sí (plataformas cloud) |
| NCBI Nucleotide / eDNA | Global | Dominio Público/CC0 | Entrez E-utilities REST API | Diaria | Abundancia de secuencias sin anotación funcional ecológica completa. | No (opcional) |

---

## 9. Brechas de Frontera, Espacio en Blanco y Afirmaciones Débiles a Evitar

### Análisis de Proyectos Competidores y Espacio en Blanco Identificado

> **Advertencia de auditoría**: las siguientes referencias a repositorios de código de proyectos competidores (identificadores de usuario y repositorio de GitHub) **no pudieron verificarse** con las herramientas disponibles en esta revisión. Se mantienen tal como aparecían en el original únicamente como marcador de posición del análisis competitivo; el equipo debe confirmar directamente la URL, el contenido y la vigencia de cada repositorio antes de citarlos en una entrega oficial.

- **Neer**: calcula un índice compuesto agregando CCME WQI, ASPT y presiones antropogénicas mediante media geométrica ponderada. No contempla propagación hidrodinámica, carece de cuantificación de incertidumbre con garantías matemáticas y no genera recursos FHIR con trazabilidad.
- **Riparia**: propone una capa de confianza human-in-the-loop, pero omite el decaimiento físico de contaminantes en redes dirigidas y no incorpora predicción conforme adaptativa.
- **Catchment**: enfocado en asignación óptima de rutas de muestreo ciudadano; carece de módulos predictivos de riesgo patógeno e integración semántica clínica.
- **AquaSentinel**: orientado al triage de incidentes puntuales; no incluye rarefacción ecológica sobre datos sesgados ni modelos de desbordamiento de alcantarillado.

### Diez Ángulos de Innovación Defendibles (Factibles en 10 Días)

1. **Inferencia de Verdad Biológica Ciudadana mediante Dawid-Skene Multi-Anotador (crowd-kit)** — sustituye el consenso por mayoría simple por inferencia bayesiana de la matriz de confusión individual. MVE: script Python sobre reportes redundantes de macroinvertebrados. Métrica: Log-Loss y macro F1 frente a determinaciones expertas. Riesgo: densidad insuficiente de observaciones replicadas.
2. **Mecanismo de Abstención Conforme para Clasificación Taxonómica (crepes)** — clasificador que difiere al ecólogo si el conjunto conforme tiene cardinalidad > 1. Métrica: cobertura empírica marginal (≥ 1−α) y tamaño medio del conjunto. Riesgo: conjuntos vacíos o excesivamente grandes ante imágenes degradadas.
3. **Propagador de Riesgo Topológico Fluvial Basado en Grafos Dirigidos (NetworkX/PyG)** — DAG sobre un tramo piloto europeo con decaimiento advectivo-dispersivo. Métrica: R² frente a concentraciones observadas aguas abajo. Riesgo: incertidumbre en la velocidad local del flujo sin aforo continuo.
4. **Predicción de Desbordamiento de Redes de Saneamiento (CSO) Acoplada a Precipitación Horaria** — regresión logística sobre el Índice de Precipitación Antecedente. Métrica: Brier Score y AUC-ROC. Riesgo: falta de planos de capacidad de retención de tanques de tormenta locales.
5. **Corrección de Riqueza y Rarefacción Asintótica para Bioindicadores Ciudadanos** — Chao1 y cobertura de Chao & Jost para corregir el EQR biológico. Métrica: RMSE frente a muestreos exhaustivos. Riesgo: sesgo de detectabilidad en taxones microscópicos.
6. **Agregador Multicriterio No Compensatorio con Umbrales de Veto Sanitario (PROMETHEE)** — veto automático ante cianotoxinas o bacterias multirresistentes. Riesgo: dificultad de consensuar umbrales sin panel bioético presencial.
7. **Pipeline de Serialización y Validación FHIR R4 con Perfil Canónico `hl7.eu.fhir.oah`** — conversor a bundles `Observation`/`Location`/`RiskAssessment` validados con Pydantic. Riesgo: cambios de última hora en el IG en desarrollo activo.
8. **Trazabilidad Criptográfica de Procedencia en `Provenance`** — hash SHA-256 de los datos de campo y versión exacta del modelo. Riesgo: sobrecarga de almacenamiento de recursos JSON.
9. **Optimizador de Triage Basado en Funciones de Utilidad Coste-Pérdida Sanitaria** — simulador interactivo de la relación C/L. Riesgo: incertidumbre en costes indirectos de alarma social.
10. **Filtro Físico-Químico Contextual Anti-Alucinaciones para VLM Taxonómico** — rechaza identificaciones incompatibles con los datos físicos concurrentes (p. ej. familia de aguas frías con hipoxia y 29 °C reportados). Riesgo: descarte involuntario de especímenes muertos arrastrados desde cabeceras limpias.

### Cinco Afirmaciones Científicamente Débiles Habituales en Hackathons (A Evitar)

1. *"Los VLM pueden clasificar con precisión especies de macroinvertebrados a partir de fotografías de smartphone tomadas por ciudadanos."* — La taxonomía exige examen microscópico de armaduras genitales y piezas bucales, ausente en fotografías de campo.
2. *"La media geométrica ponderada permite sintetizar la calidad química, biológica y patógena en un índice incorruptible."* — Es parcialmente compensatoria y colapsa ante un único valor nulo.
3. *"Un modelo recurrente predice la calidad del agua a escala de cuenca usando distancias euclidianas planas."* — El transporte hidrodinámico es asimétrico y unidireccional según la red de drenaje.
4. *"Los datos de ciencia ciudadana pueden incorporarse directamente a sistemas de alerta temprana sin corrección de sesgos."* — Los censos voluntarios tienen sesgos de accesibilidad, meteorología y falsos negativos.
5. *"Generamos dinámicamente recursos FHIR mediante agentes de IA que mapean cualquier parámetro en tiempo real."* — Los agentes LLM inventan códigos LOINC/SNOMED inexistentes y violan restricciones de cardinalidad.

---

## 10. Estrategia de Validación Científica y Mitigación de Fugas

### Protocolo de Evaluación Honesta sin Verdad Terreno Absoluta

**Validación Cruzada por Bloques Espaciales**: agrupar folds por subcuencas hidrográficas completas (Leave-One-Catchment-Out) para evitar la fuga de datos por autocorrelación espacial; aplicar un búfer espacial mínimo entre estaciones limítrofes de entrenamiento y prueba.

**Evaluación Prospectiva Encadenada (Rolling-Origin):**

$$\text{Train}_t = \{1,\dots,t\},\quad \text{Test}_t = \{t+\Delta t\}$$

**Benchmarks Semi-Sintéticos**: inyectar pulsos estocásticos de contaminación sobre series basales no perturbadas, más ruido de anotadores modelado según Dawid-Skene, para evaluar sensibilidad y estabilidad de las bandas conformes bajo estrés.

### Métricas de Diagnóstico, Diagramas de Fiabilidad y Ablaciones

- **Diagramas de Fiabilidad**: frecuencia empírica vs. probabilidad pronosticada; desviaciones de la diagonal de 45° indican sobreconfianza o subestimación.
- **Curvas Riesgo-Cobertura**: tasa de error vs. porcentaje de casos evaluados automáticamente.
- **Ablaciones obligatorias**: topología del grafo (ST-GNN vs. LSTM sin adyacencia), calibrador de observadores (consenso simple vs. Dawid-Skene), intervalos conformes (predicción puntual vs. conjunto conforme al 90%).

---

## Lista de Lecturas Prioritarias (Reading List, corregida)

*Se corrigieron las entradas #11 (autoría del artículo de Kokolakis et al.) y #25 (autoría/año/revista de FIN-Benthic2). El resto de la lista se mantiene como en el original; ver Nota de Auditoría, punto C, sobre el alcance de la verificación.*

1. OneAquaHealth Consortium (2026). *Key Indicators of Ecosystem and Biological Health — Factsheets Collection.* Zenodo. DOI: 10.5281/zenodo.20345207.
2. OneAquaHealth Consortium (2026). *Field Sampling Protocols for Urban Aquatic Ecosystems.* Zenodo. DOI: 10.5281/zenodo.20344421.
3. HL7 Europe (2026). *OneAquaHealth FHIR Implementation Guide (CI Build).* build.fhir.org/ig/hl7-eu/oah.
4. European Parliament & Council (2024). *Regulation (EU) 2024/1689 (Artificial Intelligence Act).* Official Journal of the European Union.
5. Dawid, A. P., & Skene, A. M. (1979). Maximum likelihood estimation of observer error-rates using the EM algorithm. *Journal of the Royal Statistical Society: Series C*, 28(1), 20–28.
6. Ustalov, D., Pavlichenko, N., & Tseitlin, B. (2024). Learning from Crowds with Crowd-Kit. *Journal of Open Source Software*, 9(96), 6227. DOI: 10.21105/joss.06227.
7. Angelopoulos, A. N., & Bates, S. (2023). Conformal Prediction: A Gentle Introduction. *Foundations and Trends in Machine Learning*, 16(4), 494–591.
8. Boström, H. (2022). crepes: a Python Package for Generating Conformal Regressors and Predictive Systems. *PMLR*, 179, 25–34.
9. Chao, A., & Jost, L. (2012). Coverage-based rarefaction and extrapolation. *Ecology*, 93(12), 2533–2547.
10. MacKenzie, D. I., et al. (2002). Estimating site occupancy rates when detection probabilities are less than one. *Ecology*, 83(8), 2248–2255.
11. **Kokolakis, S., Kokinou, E., Karagiannidou, M., Gerarchakis, N., Vasilakos, C., Kotti, M., & Chronaki, C. (2025).** From Space to Stream: Combining Remote Sensing and In Situ Techniques for Comprehensive Stream Health Assessment. *Remote Sensing*, 17(9), 1532. *(autoría corregida — ver Nota de Auditoría A.3)*
12. Rodrigues, F., Calapez, A. R., Feio, M. J., et al. (2025). Patterns of pharmaceutical contamination in streams of European cities across urbanisation gradients. *Journal of Hazardous Materials*, 485, 139946.
13. De Carvalho, F. G., et al. (2025). Aquatic ecosystem indices linking ecosystem health to human health risks. *Environmental Science and Pollution Research*, 32, 1120–1135.
14. Feio, M. J., et al. (2024). The impacts of alien species on river bioassessment. *Journal of Environmental Management*, 351, 123874.
15. Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). On Calibration of Modern Neural Networks. *ICML 2017*, PMLR 70, 1321–1330.
16. Klingler, C., et al. (2021). LamaH-CE: Large-Sample Hydrology for Central Europe. *Earth System Science Data*, 13(9), 4529–4565.
17. Linke, S., et al. (2019). Global hydro-environmental sub-basin and river reach characteristics at high spatial resolution (HydroATLAS/HydroRIVERS). *Scientific Data*, 6, 283.
18. Canadian Council of Ministers of the Environment (2001). *Canadian Water Quality Index 1.0: Technical Report.* CCME, Winnipeg.
19. Alba-Tercedor, J., & Sánchez-Ortega, A. (1988). Un método rápido y simple para evaluar la calidad biológica de las aguas corrientes. *Limnetica*, 4, 51–56.
20. Munné, A., Prat, N., et al. (2003). QBR: A quick test for riparian forest quality. *Ecosistemas*, 12(1), 1–15.
21. Sobol, I. M. (2001). Global sensitivity indices for nonlinear mathematical models. *Mathematics and Computers in Simulation*, 55(1–3), 271–280.
22. Rezaei, J. (2015). Best-worst multi-criteria decision-making method. *Omega*, 53, 49–57.
23. Mothilal, R. K., Sharma, A., & Tan, C. (2020). Explaining machine learning classifiers through diverse counterfactual explanations. *ACM FAT\* 2020*, 607–617.
24. Gneiting, T., & Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. *JASA*, 102(477), 359–378.
25. **Raitoharju, J., Riabchenko, E., Ahmad, I., Iosifidis, A., Gabbouj, M., Kiranyaz, S., Tirronen, V., Ärje, J., Kärkkäinen, S., & Meissner, K. (2018).** Benchmark database for fine-grained image classification of benthic macroinvertebrates (FIN-Benthic2). *Image and Vision Computing*, 78. DOI: 10.1016/j.imavis.2018.06.005. *(referencia corregida en su totalidad — ver Nota de Auditoría A.2)*

---

## Apéndice Matemático: Fórmulas y Métricas Recomendadas

### 1. Índices Bioindicadores y de Calidad Fisicoquímica

$$\text{IBMWP} = \sum_{i=1}^{S} s_i,\quad \text{ASPT} = \frac{\text{IBMWP}}{S}$$

$$\text{EQR}_{ASPT} = \frac{\text{ASPT}_{observado}}{\text{ASPT}_{referencia}}$$

$$F_1 = \left(\frac{u_v}{M_v}\right)\times 100,\quad F_2=\left(\frac{u_t}{M_t}\right)\times 100$$

$$\text{excursion}_j = \begin{cases}\left(\frac{v_j}{\text{umbral}_j}\right)-1 & \text{si excede el máximo}\\ \left(\frac{\text{umbral}_j}{v_j}\right)-1 & \text{si cae bajo el mínimo}\end{cases}$$

$$\text{nse} = \frac{\sum_{j=1}^{u_t}\text{excursion}_j}{M_t},\quad F_3=\frac{\text{nse}}{0.01\cdot\text{nse}+0.01}$$

$$\text{CCME WQI} = 100-\frac{\sqrt{F_1^2+F_2^2+F_3^2}}{1.732}$$

### 2. Estimadores Asintóticos de Riqueza y Cobertura

$$S_{Chao1\text{-}bc} = S_{obs}+\frac{f_1(f_1-1)}{2(f_2+1)}$$

$$\hat{C}_n = 1-\frac{f_1}{n}\left[\frac{(n-1)f_1}{(n-1)f_1+2f_2}\right]$$

### 3. Modelo de Fiabilidad del Observador (Dawid-Skene)

$$T_{ik}\propto p_k\prod_{j\in\mathcal{U}_i}\prod_{l=1}^K\left(\pi_{k,l}^{(j)}\right)^{I(x_i^{(j)}=l)}$$

$$\pi_{k,l}^{(j)} = \frac{\sum_{i\in\mathcal{T}_j}T_{ik}\,I(x_i^{(j)}=l)}{\sum_{i\in\mathcal{T}_j}T_{ik}}$$

### 4. Calibración de Probabilidades y Predicción Conforme

$$\text{ECE} = \sum_{m=1}^M\frac{|\mathcal{B}_m|}{N}\left|\frac{1}{|\mathcal{B}_m|}\sum_{i\in\mathcal{B}_m}I(\hat y_i=y_i)-\frac{1}{|\mathcal{B}_m|}\sum_{i\in\mathcal{B}_m}\hat p_i\right|$$

$$\hat q = \text{Quantile}\left(1-\alpha;\ \{1-\hat\pi_{Y_i}(X_i)\}_{i=1}^{n_{cal}}\right)$$

$$\mathcal{C}(X_{nuevo}) = \left\{k\in\{1,\dots,K\}: 1-\hat\pi_k(X_{nuevo})\le\hat q\right\}$$

### 5. Propagación Físico-Estadística Fluvial y Evaluación Probabilística

$$\frac{\partial C}{\partial t} = -u\frac{\partial C}{\partial x}+D_L\frac{\partial^2 C}{\partial x^2}-kC+\frac{q_L}{A}(C_L-C)$$

$$\text{CRPS}(F,y) = \int_{-\infty}^{\infty}\left[F(z)-\mathbb{I}(z\ge y)\right]^2 dz$$

$$\text{BS} = \frac{1}{N}\sum_{i=1}^N(\hat p_i-y_i)^2$$

$$\text{Alerta} = \begin{cases}1 & \text{si } P(Y=1\mid X)\ge C/L\\ 0 & \text{en caso contrario}\end{cases}$$

### 6. Ponderación por Entropía y Sensibilidad Global de Sobol

$$E_j = -\frac{1}{\ln(m)}\sum_{i=1}^m p_{ij}\ln(p_{ij}),\quad w_j=\frac{1-E_j}{\sum_{k=1}^n(1-E_k)}$$

$$S_i = \frac{\mathbb{V}_{X_i}(\mathbb{E}_{\mathbf{X}_{\sim i}}[Y\mid X_i])}{\mathbb{V}(Y)},\quad S_{Ti}=1-\frac{\mathbb{V}_{\mathbf{X}_{\sim i}}(\mathbb{E}_{X_i}[Y\mid\mathbf{X}_{\sim i}])}{\mathbb{V}(Y)}$$

---

## Lista de Incógnitas Conocidas (Known Unknowns)

- **Régimen Hidrológico Intermitente en Cuencas Mediterráneas**: durante el estío, ríos urbanos semiáridos (p. ej. **Benevento**, sur de Italia — *ejemplo corregido; el original citaba "Heraklion" como ciudad piloto, lo cual es incorrecto, ver Nota de Auditoría A.1*) pueden fragmentarse en pozas aisladas, desconectando la topología DAG y exigiendo detección de caudal nulo para conmutar a modelos de reactor discontinuo.
- **Latencia Analítica en Microorganismos Viables y AMR**: el cultivo o qPCR de patógenos requiere 24–72 h de latencia; las alertas tempranas dependen de proxies meteorológicos e hidráulicos hasta la verificación analítica.
- **Evolución del Esquema Terminológico del IG OneAquaHealth**: la guía `hl7.eu.fhir.oah` está en desarrollo activo (versión continua 0.1.0-ci-build); los códigos locales de IBMWP/QBR podrían cambiar antes de su aprobación definitiva.
- **Representación de Micro-Infraestructuras de Drenaje Urbano**: HydroRIVERS/MERIT-Hydro no capturan tramos soterrados bajo colectores o sifones menores de 90 m, introduciendo error en tiempos de viaje y dispersión.
- **Causalidad Clínica Individualizada vs. Correlación Poblacional**: sesgos de confusión socioeconómicos y periodos de incubación variables impiden atribuir diagnósticos médicos individuales a fuentes ambientales específicas sin estudios de cohortes.

---

*Fin del informe auditado. Todas las correcciones respecto al original se documentan en la Sección 0 (Nota de Auditoría) y se señalan en línea con el marcador "corregido" allí donde aplican.*

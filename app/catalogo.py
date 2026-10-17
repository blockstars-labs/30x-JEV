"""Categorías que usa 30X para describir a las personas que llegan.

Las etiquetas en español salen tal cual del archivo de perfiles de demo que compartió 30X.
Las descripciones en inglés son las que ve JEV: la documentación de TypeSafe indica que el
modelo rinde mejor con instrucciones y criterios en inglés, aunque el estado esté en español.

`claves_mock` solo lo usa el JEV simulado (modo mock); el JEV real nunca lo ve.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Opcion:
    id: str
    etiqueta: str          # nombre de la categoría en 30X
    descripcion: str       # criterio que ve JEV
    claves_mock: tuple[str, ...] = field(default=())


ROLES = [
    Opcion("fundador", "Fundador, socio o CEO",
           "The person founded, co-founded, owns or is a partner of the business, or is its CEO.",
           ("fundador", "fundé", "cofundador", "socio", "ceo", "dueño", "mi empresa", "mi negocio")),
    Opcion("c_level", "Director, VP o C-level (no dueño)",
           "The person is a director, VP or C-level executive (CFO, COO, CMO, CTO...) employed by a company they do not own.",
           ("director", "directora", "vp", "vicepresidente", "cfo", "coo", "cmo", "cto")),
    Opcion("lider_comercial", "Líder comercial o de ventas",
           "The person leads or manages a sales, commercial or business development team.",
           ("ventas", "comercial", "head of sales", "equipo de ventas", "desarrollo de negocio")),
    Opcion("gerente", "Gerente o jefe de área",
           "The person is a manager or head of a non-sales area (operations, marketing, HR, finance, projects...).",
           ("gerente", "jefe", "jefa", "coordinador", "líder de área", "head of")),
    Opcion("tecnico", "Perfil técnico (ingeniería, datos, producto)",
           "The person works in a technical role: software engineering, data, analytics or product.",
           ("ingeniero", "ingeniera", "desarrollador", "datos", "data", "producto", "software")),
    Opcion("otro", "Otro rol",
           "The person states a role that fits none of the other options (for example student, freelancer, job seeker).",
           ("estudiante", "freelance", "busco empleo", "universidad")),
    Opcion("sin_dato", "Sin dato de rol",
           "The text does not say what the person's role or job title is.",
           ()),
]

DOLORES = [
    Opcion("procesos_manuales", "Procesos manuales y rezago tecnológico",
           "Too much manual work, spreadsheets or outdated tools; the business lags behind technologically.",
           ("manual", "excel", "a mano", "atrasados", "tecnología", "procesos")),
    Opcion("claridad_estrategica", "Falta de claridad estratégica para escalar",
           "Unclear strategy or priorities to grow and scale the business.",
           ("estrategia", "escalar", "no sé por dónde", "prioridades", "rumbo")),
    Opcion("sin_proceso_comercial", "No tiene proceso comercial estructurado",
           "There is no defined, repeatable sales process, pipeline or sales methodology.",
           ("proceso comercial", "embudo", "pipeline", "sin proceso", "desordenado")),
    Opcion("referidos", "Vive de referidos y prospecta a mano",
           "New clients come almost only from referrals or word of mouth; prospecting is manual.",
           ("referidos", "boca a boca", "recomendaciones", "prospectar")),
    Opcion("dueno_cuello_botella", "El dueño es el cuello de botella y no delega",
           "The owner is involved in everything, cannot delegate and the business depends on them.",
           ("cuello de botella", "delegar", "todo pasa por mí", "depende de mí")),
    Opcion("ventas_estancadas", "Ventas estancadas o cayendo",
           "Sales are flat or declining.",
           ("estancadas", "cayendo", "bajaron", "no crecen")),
    Opcion("capital", "Capital y flujo de caja para crecer",
           "Lack of capital or cash flow is limiting growth.",
           ("capital", "flujo de caja", "caja", "financiación", "inversión")),
    Opcion("equipo", "Equipo: contratar, retener y vencer la resistencia al cambio",
           "Problems hiring, retaining people or getting the team to accept change.",
           ("contratar", "retener", "resistencia", "talento", "rotación")),
    Opcion("expansion_sin_metodo", "Expansión internacional sin método",
           "Trying to expand to other countries without a clear method.",
           ("otros países", "internacional", "expandir", "nuevos mercados")),
    Opcion("ninguno", "No declaró ningún dolor",
           "The text does not describe any business problem or pain.",
           ()),
]

OBJETIVOS = [
    Opcion("automatizar_ia", "Automatizar con IA",
           "Wants to automate tasks or processes in their business using AI.",
           ("automatizar", "automatización", "agentes", "ia en mi empresa")),
    Opcion("vender_mas", "Vender más",
           "Wants to increase sales or get more clients.",
           ("vender más", "más clientes", "aumentar ventas", "facturar")),
    Opcion("formarse_ia", "Formarse (sobre todo en IA)",
           "Wants to learn or get trained personally, mainly about AI.",
           ("aprender", "formarme", "capacitarme", "entender la ia", "curso")),
    Opcion("expandirse", "Expandirse a otros países",
           "Wants to take the business to other countries.",
           ("otros países", "estados unidos", "expandirme", "internacionalizar")),
    Opcion("maquina_ventas", "Construir una máquina de ventas",
           "Wants to build a structured, repeatable sales system or team.",
           ("máquina de ventas", "sistema comercial", "equipo comercial", "proceso de ventas")),
    Opcion("levantar_capital", "Levantar capital",
           "Wants to raise investment or funding.",
           ("levantar capital", "inversionistas", "ronda", "fundraising")),
    Opcion("red_pares", "Entrar a una red de pares",
           "Wants to join a network or community of peers (other founders or executives).",
           ("red", "comunidad", "pares", "networking", "otros fundadores")),
    Opcion("liderazgo", "Desarrollar liderazgo y equipo",
           "Wants to develop their leadership skills or their team.",
           ("liderazgo", "líder", "desarrollar a mi equipo")),
    Opcion("delegar", "Delegar y pasar a un rol estratégico",
           "Wants to step out of operations, delegate and focus on strategy.",
           ("delegar", "rol estratégico", "salir de la operación")),
    Opcion("transformar_modelo", "Transformar el modelo de negocio",
           "Wants to change or reinvent the business model.",
           ("modelo de negocio", "reinventar", "transformar")),
    Opcion("otro", "Otro objetivo",
           "States a goal that fits none of the other options, or states no goal at all.",
           ()),
]

# Programas que 30X sugiere hoy (columna "Programa sugerido" del archivo de demo).
# La descripción de cada uno es una INFERENCIA a partir de los perfiles a los que se sugiere;
# hay que validarla con 30X antes de usarla fuera del prototipo.
PROGRAMAS = {
    "ai_sales": "AI Sales",
    "inmersion_ejecutiva": "Inmersión Ejecutiva",
    "sales_machine": "Sales Machine",
    "hardcore_ai": "Hardcore AI",
    "achievers": "Achievers",
    "ninguno": "Sin programa sugerido",
}

# Temas de interés que la persona marca al inscribirse (dato exacto del formulario, no lo infiere JEV).
TEMAS = ["ai", "sales", "ops", "gtm", "leadership", "marketing", "fundraising",
         "finance", "product", "pricing", "hiring", "negotiation", "retention"]

# Intención comercial: niveles de un Score, de menor a mayor. Cada nivel describe una situación.
INTENCION = [
    Opcion("sin_intencion", "Sin intención",
           "No sign of interest in buying or joining a paid program; only curiosity or free content.",
           ("gratis", "solo curiosidad", "por ahora no")),
    Opcion("explorando", "Explorando",
           "Shows general interest in the topics but no sign of evaluating a program.",
           ("me interesa", "quiero conocer", "explorando")),
    Opcion("evaluando", "Evaluando",
           "Is comparing options or asks about program content, format, dates or fit for their case.",
           ("qué incluye", "fechas", "formato", "comparando", "opciones")),
    Opcion("listo", "Listo para conversar",
           "Explicitly asks for price, a call, a proposal or how to enroll, or says they have budget to start soon.",
           ("precio", "llamada", "propuesta", "inscribirme", "presupuesto", "cuánto cuesta")),
]


def por_id(opciones: list[Opcion]) -> dict[str, Opcion]:
    return {o.id: o for o in opciones}

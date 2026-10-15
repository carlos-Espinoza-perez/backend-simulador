
DX_IRB140 = 0.247
DY_IRB140 = 0.203

ROBOTS = {
    "ABB_IRB_140": {
        "nombre": "ABB IRB 140",
        "tipo": "Antropomórfico",
        "grados_libertad": 6,
        "tipos_articulaciones": ["R", "R", "R", "R", "R", "R"],  # R = Rotacional, P = Prismática
        
        "tabla_dh": [

            [0, 352, 0, 0],       # Modificado de original para uniformidad, usa -90 en alpha internamente en IK
            [0, 0, 360, 0],
            [0, 0, 70, -90],
            [0, 380, 0, 90],
            [0, 0, 0, -90],
            [0, 65, 0, 0]
        ],
        
        "limites_articulares": [
            [-180, 180],
            [-90, 110],
            [-52, 50],
            [-200, 200],
            [-115, 115],
            [-400, 400]
        ],
        
        "archivos_stl": [
            "IRB140_-_M2004C_BASE.STL",
            "IRB140_-_M2004C_LINK1.STL",
            "IRB140_-_M2004C_LINK2.STL",
            "IRB140_-_M2004C_LINK3.STL",
            "IRB140_-_M2004C_LINK4.STL",
            "IRB140_-_M2004C_LINK5.STL",
            "IRB140_-_M2004C_LINK6.STL"
        ],
        
        "ruta_stl": "models/ABB_IRB_140",
        
        "visualizacion": {
            "escala": 0.001,
            "unidades": "mm",
            "posicion_inicial": [-DX_IRB140, 0, 0.200],
            "rotacion_inicial": [-90, 0, 0],
            "pivots": [
                [0, 0, 0],
                [DX_IRB140 + 0.065, DY_IRB140, 0],
                [DX_IRB140 + 0.140, DY_IRB140, 0.352],
                [DX_IRB140 + 0.140, DY_IRB140, 0.712],
                [DX_IRB140 + 0.070, DY_IRB140, 0.712],
                [DX_IRB140 + 0.520, DY_IRB140, 0.712],
                [DX_IRB140 + 0.515, DY_IRB140, 0.712]
            ],
            "axes": [
                [0, 0, 0],
                [0, 0, 1],
                [0, 1, 0],
                [0, 1, 0],
                [1, 0, 0],
                [0, 1, 0],
                [1, 0, 0]
            ],
            "camara": {
                "posicion": [1.2, 0.9, 1.2],
                "fov": 45,
                "min_distancia": 0.4,
                "max_distancia": 10
            }
        },
        
        "eslabones": [
            { "id": 0, "nombre": "Base", "archivo_stl": "IRB140_-_M2004C_BASE.STL", "color": "#E8E8E8" },
            { "id": 1, "nombre": "Link 1", "archivo_stl": "IRB140_-_M2004C_LINK1.STL", "color": "#E8E8E8" },
            { "id": 2, "nombre": "Link 2", "archivo_stl": "IRB140_-_M2004C_LINK2.STL", "color": "#E8E8E8" },
            { "id": 3, "nombre": "Link 3", "archivo_stl": "IRB140_-_M2004C_LINK3.STL", "color": "#E8E8E8" },
            { "id": 4, "nombre": "Link 4", "archivo_stl": "IRB140_-_M2004C_LINK4.STL", "color": "#E8E8E8" },
            { "id": 5, "nombre": "Link 5", "archivo_stl": "IRB140_-_M2004C_LINK5.STL", "color": "#C0C0C0" },
            { "id": 6, "nombre": "Link 6", "archivo_stl": "IRB140_-_M2004C_LINK6.STL", "color": "#C0C0C0" }
        ],
        
        "workspace": { "grid": { "tamaño": 10, "division": 0.1 } },
        "metadatos": { "modelo": "IRB 140" }
    },
    
    "ABB_IRB_910SC": {
        "nombre": "IRB 910SC SCARA",
        "tipo": "SCARA",
        "grados_libertad": 4,
        "tipos_articulaciones": ["R", "R", "P", "R"],  # R = Rotacional, P = Prismática (J3 es 'd' en vez de 'theta')
        
        "tabla_dh": [
            [0, 200.0, 250.0, 0],
            [0, 0.0, 200.0, 180],
            [0, 100.0, 0.0, 0],    # Inicializamos d=100.0 (Prismática)
            [0, 0.0, 0.0, 0]
        ],
        
        "limites_articulares": [
            [-140.0, 140.0],
            [-150.0, 150.0],
            [0.0, 150.0],     # Prismático límite en milímetros (mm)
            [-400.0, 400.0]
        ],
        
        "archivos_stl": [
            "IRB 910SC_IRC5C_Base_Standard_rev0.STL",
            "IRB 910SC_IRC5C_Arm1_650_rev0.STL",
            "IRB 910SC_IRC5C_Arm2_650_rev0.STL",
            "IRB 910SC_IRC5C_shaft_650_rev0.STL"
        ],
        "ruta_stl": "models/IRB_910SC_650",
        
        "visualizacion": {
            "escala": 0.001,
            "unidades": "mm",
            "posicion_inicial": [0.0, 0.0, 0.0],
            "rotacion_inicial": [-90, 0, 0],
            "pivots": [
                [0, 0, 0],
                [0.005, -0.01, 0.200],   # J1 Height (Base a Arm1)
                [0.410, -0.01, 0.200],   # J2 (Arm1 a Arm2)
                [0.675, -0.01, 0.220],   # J3 (Shaft Translation)  <- Z corregido a 0.220
                [0.675, -0.01, 0.220],   # J4 (Shaft Rotation)     <- Z corregido a 0.220
            ],
            "axes": [
                [0, 0, 0],
                [0, 0, 1],               # J1 Z+
                [0, 0, 1],               # J2 Z+
                [0, 0, -1],              # J3 Translación Z-
                [0, 0, -1]               # J4 Rotación Z-
            ],
            "camara": {
                "posicion": [1.5, 1.5, 1.5], "fov": 50, "min_distancia": 0.3, "max_distancia": 5
            }
        },
        
        "eslabones": [
            { "id": 0, "nombre": "Base", "archivo_stl": "IRB 910SC_IRC5C_Base_Standard_rev0.STL", "color": "#455a64", "posicion_local": [-0.195, -0.09, 0] },
            { "id": 1, "nombre": "Link 1", "archivo_stl": "IRB 910SC_IRC5C_Arm1_650_rev0.STL", "color": "#64b5f6", "posicion_local": [-0.065, -0.095, 0] },
            { "id": 2, "nombre": "Link 2", "archivo_stl": "IRB 910SC_IRC5C_Arm2_650_rev0.STL", "color": "#64b5f6", "posicion_local": [0.025, -0.1, 0] },
            { "id": 3, "nombre": "Shaft", "archivo_stl": "IRB 910SC_IRC5C_shaft_650_rev0.STL", "color": "#4caf50", "posicion_local": [0.025, -0.03, 0] }
        ],
        
        "workspace": { "grid": { "tamaño": 5, "division": 0.1 } },
        "metadatos": { "modelo": "IRB 910SC" }
    },

    "IRB_14000": {
        "nombre": "ABB IRB 14000 (YuMi)",
        "tipo": "Colaborativo",
        "grados_libertad": 7,
        "tipos_articulaciones": ["R", "R", "R", "R", "R", "R", "R"],
        
        "tabla_dh": [
            [0, 166.0, 30.0, -90],
            [0, 0.0, 30.0, 90],
            [0, 251.5, 40.0, -90],
            [0, 0.0, 40.0, 90],
            [0, 265.0, 0.0, -90],
            [0, 0.0, 0.0, 90],
            [0, 36.0, 0.0, 0]
        ],
        
        "limites_articulares": [
            [-168.5, 168.5],
            [-143.5, 43.5],
            [-168.5, 168.5],
            [-123.5, 80.0],
            [-290.0, 290.0],
            [-88.0, 138.0],
            [-229.0, 229.0]
        ],
        
        "archivos_stl": [
            "body.stl",
            "link_1.stl",
            "link_2.stl",
            "link_3.stl",
            "link_4.stl",
            "link_5.stl",
            "link_6.stl",
            "link_7.stl"
        ],
        "ruta_stl": "models/IRB_1400",
        
        "visualizacion": {
            "escala": 0.001,
            "unidades": "mm",
            "posicion_inicial": [0.0, 0.0, 0.0],
            "rotacion_inicial": [-90, 0, 0],
            "pivots": [
                [0, 0, 0],
                [0.0, 0.0, 0.0],
                [0.03, 0.0, 0.166],
                [0.06, 0.0, 0.166],
                [0.10, 0.0, 0.4175],
                [0.14, 0.0, 0.4175],
                [0.14, 0.0, 0.6825],
                [0.14, 0.0, 0.6825],
                [0.14, 0.0, 0.7185]
            ],
            "axes": [
                [0, 0, 0],
                [0, 0, 1],
                [0, 1, 0],
                [0, 0, 1],
                [0, 1, 0],
                [0, 0, 1],
                [0, 1, 0],
                [0, 0, 1]
            ],
            "camara": {
                "posicion": [1.5, 1.5, 1.5], "fov": 50, "min_distancia": 0.3, "max_distancia": 5
            }
        },
        
        "eslabones": [
            { "id": 0, "nombre": "Body", "archivo_stl": "body.stl", "color": "#E8E8E8" },
            { "id": 1, "nombre": "Link 1", "archivo_stl": "link_1.stl", "color": "#E8E8E8" },
            { "id": 2, "nombre": "Link 2", "archivo_stl": "link_2.stl", "color": "#E8E8E8" },
            { "id": 3, "nombre": "Link 3", "archivo_stl": "link_3.stl", "color": "#E8E8E8" },
            { "id": 4, "nombre": "Link 4", "archivo_stl": "link_4.stl", "color": "#E8E8E8" },
            { "id": 5, "nombre": "Link 5", "archivo_stl": "link_5.stl", "color": "#E8E8E8" },
            { "id": 6, "nombre": "Link 6", "archivo_stl": "link_6.stl", "color": "#C0C0C0" },
            { "id": 7, "nombre": "Link 7", "archivo_stl": "link_7.stl", "color": "#C0C0C0" }
        ],
        
        "workspace": { "grid": { "tamaño": 5, "division": 0.1 } },
        "metadatos": { "modelo": "IRB 1400" }
    }
}

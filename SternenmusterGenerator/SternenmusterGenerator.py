# -*- coding: utf-8 -*-
"""
Sternenmuster-Generator fuer die parametrische Teelicht-Rakete
==============================================================

Erzeugt zufaellig verteilte Durchbrueche (Punkte, Sterne, Galaxien, Saturne)
im Raketenrumpf. Das Muster ist reproduzierbar: gleicher SEED -> gleiches Muster.

VERWENDUNG IN FUSION
--------------------
  Dienstprogramme  ->  ADD-INS  ->  Skripte und Add-Ins  ->  Reiter "Skripte"
  ->  gruenes "+"  ->  "Skript aus Geraet"  ->  diesen Ordner waehlen
  ->  Skript markieren  ->  "Ausfuehren"

Beim Ausfuehren werden ZUERST alle vorhandenen Sternen-Features geloescht
(alles mit Praefix "Sterne_" bzw. "SternEbene_") und danach neu erzeugt.
Ein neues Muster bekommst du also, indem du unten SEED aenderst und das
Skript erneut ausfuehrst. Alles andere am Modell bleibt unberuehrt.

VORAUSSETZUNGEN im aktiven Design
---------------------------------
  Skizze:     Profil_Raketenkoerper   (liefert die Aussenkontur r(z))
  Parameter:  belly_dia, fin_top_z, fin_t, win_z, win_frame_dia,
              ring_z, ring_hole_dia
"""

import adsk.core
import adsk.fusion
import math
import random
import traceback


# ===========================================================================
#  EINSTELLUNGEN  -  hier drehen, dann Skript neu ausfuehren
# ===========================================================================

SEED = 7                 # Zufalls-Startwert. Anderer Wert = anderes Muster.

# --- Wie viele Loecher, und in welchem Verhaeltnis? -----------------------
#
# Es gibt zwei Betriebsarten. Entscheidend ist STUECKZAHLEN:
#
#   STUECKZAHLEN = None   ->  ANZAHL Loecher, verteilt nach den Anteilen
#                             in FORMEN. Das genaue Verhaeltnis schwankt
#                             leicht, weil gewuerfelt wird.
#
#   STUECKZAHLEN = {...}  ->  exakt diese Stueckzahlen je Form. ANZAHL und
#                             die Anteile in FORMEN werden dann ignoriert.
#
# Beispiel fuer exakte Vorgabe:
#   STUECKZAHLEN = {'punkt': 24, 'stern': 10, 'galaxie': 7, 'saturn': 6}

STUECKZAHLEN = None

ANZAHL = 100              # Nur wirksam, wenn STUECKZAHLEN = None.

# Anteile der Formen. Werden automatisch normiert, muessen also nicht
# exakt 1.0 ergeben - 3/2/2/1 funktioniert genauso wie 0.3/0.2/0.2/0.1.
# Eine Form ganz weglassen: Anteil auf 0 setzen oder Zeile loeschen.
FORMEN = [
    ('punkt',   0.34),   # kleine Rundloecher, der Sternenhimmel-Grundton
    ('stern',   0.26),   # fuenfzackige Sterne
    ('galaxie', 0.22),   # schraege Ellipsen
    ('saturn',  0.18),   # Planet mit Ring
]

# Groessenbereiche je Form in mm (kleinste / groesste Ausdehnung).
GROESSEN = {
    'punkt':   (1.6, 3.2),
    'stern':   (4.5, 7.5),
    'galaxie': (5.0, 9.0),
    'saturn':  (7.0, 11.0),
}

Z_UNTEN = 22.0           # Unterste Hoehe fuer Loecher, mm ueber Rumpfboden.
Z_OBEN = 118.0           # Oberste Hoehe. Darueber wird die Ogive zu schmal.

EBENEN_RASTER = 15.0     # Winkelraster der Schnittebenen in Grad.
                         # Kleiner = feiner verteilt, aber mehr Features.

ABSTAND_UNTEREINANDER = 2.6   # Mindeststeg zwischen zwei Loechern, mm.
ABSTAND_BULLAUGE = 3.5        # Zusaetzlicher Abstand zum Bullaugenrahmen, mm.
ABSTAND_FINNE = 3.0           # Zusaetzlicher Abstand zur Finnenwurzel, mm.
ABSTAND_LOCHKRANZ = 3.5       # Zusaetzlicher Abstand zum Lochkranz, mm.

FINNEN_WINKEL = [0.0, 120.0, 240.0]   # Wo die Finnen sitzen, Grad.
BULLAUGEN_WINKEL = [0.0, 180.0]       # Wo die Bullaugen sitzen, Grad.

MIN_RADIUS = 7.0     # Unter diesem Rumpfradius werden keine Loecher gesetzt.
SKALIER_RADIUS = 17.0  # Ab hier werden Formen zur Spitze hin verkleinert.

MM = 0.1   # Umrechnung mm -> Fusion-Interneinheit (cm). Nicht aendern.


# ===========================================================================
#  Aussenkontur des Rumpfs
# ===========================================================================

def aussenradius_funktion(root):
    """Liest die Boegen aus Profil_Raketenkoerper und liefert r(z) in mm."""
    sk = root.sketches.itemByName('Profil_Raketenkoerper')
    if not sk:
        raise RuntimeError('Skizze "Profil_Raketenkoerper" nicht gefunden.')

    # Vorzeichen der Hoehenachse in dieser Skizze bestimmen
    probe = adsk.fusion.SketchLine.cast(sk.project(root.zConstructionAxis).item(0))
    sgn = 1.0 if (probe.geometry.endPoint.y - probe.geometry.startPoint.y) > 0 else -1.0
    probe.deleteMe()

    boegen = []
    for a in sk.sketchCurves.sketchArcs:
        g = a.geometry
        cx = g.center.x * 10.0
        cy = g.center.y * 10.0 * sgn
        r = g.radius * 10.0
        e1 = (g.startPoint.x * 10.0, g.startPoint.y * 10.0 * sgn)
        e2 = (g.endPoint.x * 10.0, g.endPoint.y * 10.0 * sgn)
        # Auf welcher Seite des Mittelpunkts liegt der Bogen?
        zweig = 1.0 if (e1[0] + e2[0]) / 2.0 > cx else -1.0
        boegen.append((cx, cy, r, zweig, min(e1[1], e2[1]), max(e1[1], e2[1])))

    def r_aussen(z):
        """Groesster Aussenradius auf Hoehe z. Innenboegen fallen dabei weg."""
        best = 0.0
        for cx, cy, r, zweig, z_lo, z_hi in boegen:
            if z_lo - 0.01 <= z <= z_hi + 0.01:
                d = r * r - (z - cy) ** 2
                if d > 0:
                    best = max(best, cx + zweig * math.sqrt(d))
        return best

    return r_aussen


# ===========================================================================
#  Verteilung wuerfeln
# ===========================================================================

def verteilung_berechnen(root, up):
    """Wuerfelt Positionen und gruppiert sie auf Winkelebenen."""

    def p(name):
        """Parameterwert in mm."""
        par = up.itemByName(name)
        if not par:
            raise RuntimeError('Parameter "%s" fehlt im Design.' % name)
        return par.value * 10.0

    r_aussen = aussenradius_funktion(root)

    fin_top = p('fin_top_z')
    fin_t = p('fin_t')
    win_z = p('win_z')
    win_r = p('win_frame_dia') / 2.0
    ring_z = p('ring_z')
    ring_d = p('ring_hole_dia')

    rng = random.Random(SEED)

    if STUECKZAHLEN:
        # Exakte Vorgabe: Pool aus genau diesen Formen, gemischt.
        # Eine Form wird erst aus dem Pool genommen, wenn sie Platz gefunden hat.
        pool = []
        for name, n in STUECKZAHLEN.items():
            pool.extend([name] * int(n))
        rng.shuffle(pool)
        ziel = len(pool)

        def naechste_form():
            return pool[0] if pool else None

        def form_verbraucht(name):
            pool.remove(name)
    else:
        # Anteile: Gewichte normieren und gewichtet ziehen.
        summe_gewichte = sum(g for _, g in FORMEN if g > 0)
        if summe_gewichte <= 0:
            raise RuntimeError('In FORMEN hat keine Form einen Anteil groesser 0.')
        verteilung = [(n, g / summe_gewichte) for n, g in FORMEN if g > 0]
        ziel = ANZAHL

        def naechste_form():
            x = rng.random()
            summe = 0.0
            for name, anteil in verteilung:
                summe += anteil
                if x <= summe:
                    return name
            return verteilung[-1][0]

        def form_verbraucht(name):
            pass

    gesetzt = []
    versuche = 0

    while len(gesetzt) < ziel and versuche < 40000:
        versuche += 1
        z = rng.uniform(Z_UNTEN, Z_OBEN)
        winkel = rng.uniform(0.0, 360.0)
        r = r_aussen(z)
        if r < MIN_RADIUS:
            continue

        form = naechste_form()
        if form is None:
            break
        if form not in GROESSEN:
            raise RuntimeError('Fuer die Form "%s" fehlt ein Eintrag in GROESSEN.' % form)
        groesse = rng.uniform(*GROESSEN[form])
        if r < SKALIER_RADIUS:
            groesse *= max(0.45, r / SKALIER_RADIUS)
        if groesse < 1.4:
            continue

        frei = True

        # Abstand zu den Bullaugen
        for a in BULLAUGEN_WINKEL:
            du = math.radians((winkel - a + 180) % 360 - 180) * r
            if math.hypot(du, z - win_z) < win_r + groesse / 2.0 + ABSTAND_BULLAUGE:
                frei = False
                break

        # Abstand zu den Finnen, nur solange die Finnen reichen
        if frei and z < fin_top + 5.0:
            for a in FINNEN_WINKEL:
                du = abs(math.radians((winkel - a + 180) % 360 - 180)) * r
                if du < fin_t / 2.0 + groesse / 2.0 + ABSTAND_FINNE:
                    frei = False
                    break

        # Abstand zum Lochkranz
        if frei and abs(z - ring_z) < ring_d / 2.0 + groesse / 2.0 + ABSTAND_LOCHKRANZ:
            frei = False

        # Abstand zu bereits gesetzten Loechern
        if frei:
            for (z2, w2, g2, f2) in gesetzt:
                r_mittel = (r + r_aussen(z2)) / 2.0
                du = math.radians((winkel - w2 + 180) % 360 - 180) * r_mittel
                if math.hypot(du, z - z2) < (groesse + g2) / 2.0 + ABSTAND_UNTEREINANDER:
                    frei = False
                    break

        if frei:
            gesetzt.append((z, winkel, groesse, form))
            form_verbraucht(form)

    # Auf Winkelebenen gruppieren, Restwinkel wird zum seitlichen Versatz
    ebenen = {}
    for z, winkel, groesse, form in gesetzt:
        ebene = round(winkel / EBENEN_RASTER) * EBENEN_RASTER % 360.0
        rest = math.radians((winkel - ebene + 180) % 360 - 180)
        versatz = r_aussen(z) * math.sin(rest)
        ebenen.setdefault(ebene, []).append(
            (versatz, z, groesse, form, rng.random()))

    return gesetzt, ebenen, versuche


# ===========================================================================
#  Formen als Punktlisten (Koordinaten relativ zum Lochmittelpunkt, mm)
# ===========================================================================

def form_punkte(form, groesse, drehung):
    punkte = []

    if form == 'stern':
        # Fuenfzackiger Stern: abwechselnd Aussen- und Innenradius
        r_aussen = groesse / 2.0
        r_innen = r_aussen * 0.40
        for i in range(10):
            a = drehung + math.pi * i / 5.0
            r = r_aussen if i % 2 == 0 else r_innen
            punkte.append((r * math.cos(a), r * math.sin(a)))

    elif form == 'galaxie':
        # Schraege Ellipse
        a_halb = groesse / 2.0
        b_halb = groesse * 0.21
        t = drehung
        for i in range(28):
            phi = 2 * math.pi * i / 28.0
            x = a_halb * math.cos(phi)
            y = b_halb * math.sin(phi)
            punkte.append((x * math.cos(t) - y * math.sin(t),
                           x * math.sin(t) + y * math.cos(t)))

    elif form == 'saturn':
        # Silhouette = Vereinigung aus Planetenkreis und schraegem Ellipsenring.
        # Fuer jeden Winkel der groessere der beiden Radien.
        r_planet = groesse * 0.27
        ring_a = groesse * 0.50
        ring_b = groesse * 0.115
        neigung = drehung * 0.4 - 0.35
        for i in range(44):
            phi = 2 * math.pi * i / 44.0
            phi_rel = phi - neigung
            nenner = (math.cos(phi_rel) / ring_a) ** 2 + (math.sin(phi_rel) / ring_b) ** 2
            r_ring = 1.0 / math.sqrt(nenner) if nenner > 0 else 0.0
            r = max(r_planet, r_ring)
            punkte.append((r * math.cos(phi), r * math.sin(phi)))

    return punkte


# ===========================================================================
#  Geometrie erzeugen
# ===========================================================================

def altes_muster_loeschen(root):
    for f in list(root.features):
        if f.name.startswith('Sterne_'):
            f.deleteMe()
    for s in list(root.sketches):
        if s.name.startswith('Sterne_'):
            s.deleteMe()
    for p in list(root.constructionPlanes):
        if p.name.startswith('SternEbene_'):
            p.deleteMe()


def muster_erzeugen(root, ebenen):
    extrudes = root.features.extrudeFeatures
    planes = root.constructionPlanes
    erzeugt = 0
    uebersprungen = 0

    for ebene in sorted(ebenen.keys()):
        eintraege = ebenen[ebene]

        # Schnittebene: die YZ-Ebene um die Z-Achse gedreht.
        # Ihre Normale zeigt damit radial nach aussen.
        pi = planes.createInput()
        pi.setByAngle(root.zConstructionAxis,
                      adsk.core.ValueInput.createByString('%.4f deg' % ebene),
                      root.yZConstructionPlane)
        pl = planes.add(pi)
        pl.name = 'SternEbene_%03.0f' % ebene

        sk = root.sketches.add(pl)
        sk.name = 'Sterne_%03.0f' % ebene

        # Tangentialrichtung dieser Ebene in Weltkoordinaten
        tx = -math.sin(math.radians(ebene))
        ty = math.cos(math.radians(ebene))

        def punkt(u, z):
            """u = seitlicher Versatz in mm, z = Hoehe in mm."""
            return sk.modelToSketchSpace(
                adsk.core.Point3D.create(u * tx * MM, u * ty * MM, z * MM))

        for (u0, z0, groesse, form, zufall) in eintraege:
            if form == 'punkt':
                sk.sketchCurves.sketchCircles.addByCenterRadius(
                    punkt(u0, z0), groesse / 2.0 * MM)
            else:
                pts = form_punkte(form, groesse, zufall * 2 * math.pi)
                sp = [punkt(u0 + dx, z0 + dy) for dx, dy in pts]
                erste = None
                vorige = None
                for i in range(len(sp)):
                    ziel = sp[(i + 1) % len(sp)]
                    if vorige is None:
                        ln = sk.sketchCurves.sketchLines.addByTwoPoints(sp[0], ziel)
                        erste = ln
                    elif i == len(sp) - 1:
                        # Kette schliessen
                        ln = sk.sketchCurves.sketchLines.addByTwoPoints(
                            vorige.endSketchPoint, erste.startSketchPoint)
                    else:
                        ln = sk.sketchCurves.sketchLines.addByTwoPoints(
                            vorige.endSketchPoint, ziel)
                    vorige = ln
                # Hinweis: die Linien NICHT einzeln fixieren - das wuerde die
                # Koinzidenz der Kettenpunkte aufbrechen und es entstuende
                # kein geschlossenes Profil.

        # Alle Profile dieser Ebene in einem Schnitt nach aussen extrudieren
        col = adsk.core.ObjectCollection.create()
        for pr in sk.profiles:
            col.add(pr)

        try:
            ei = extrudes.createInput(
                col, adsk.fusion.FeatureOperations.CutFeatureOperation)
            ei.setDistanceExtent(
                False, adsk.core.ValueInput.createByString('belly_dia'))
            extrudes.add(ei).name = 'Sterne_Cut_%03.0f' % ebene
            erzeugt += col.count
        except:
            # Fallback: einzeln versuchen, damit ein Problemloch nicht
            # die ganze Ebene verhindert
            ok = 0
            for pr in sk.profiles:
                try:
                    ei = extrudes.createInput(
                        pr, adsk.fusion.FeatureOperations.CutFeatureOperation)
                    ei.setDistanceExtent(
                        False, adsk.core.ValueInput.createByString('belly_dia'))
                    extrudes.add(ei).name = 'Sterne_Cut_%03.0f_%d' % (ebene, ok)
                    ok += 1
                except:
                    uebersprungen += 1
            erzeugt += ok

    return erzeugt, uebersprungen


# ===========================================================================
#  Einstieg
# ===========================================================================

def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        des = adsk.fusion.Design.cast(app.activeProduct)
        if not des:
            ui.messageBox('Kein aktives Fusion-Design gefunden.')
            return

        root = des.rootComponent
        up = des.userParameters

        altes_muster_loeschen(root)
        gesetzt, ebenen, versuche = verteilung_berechnen(root, up)
        erzeugt, uebersprungen = muster_erzeugen(root, ebenen)

        zaehler = {}
        for _, _, _, form in gesetzt:
            zaehler[form] = zaehler.get(form, 0) + 1
        aufstellung = ', '.join('%d %s' % (n, f) for f, n in sorted(zaehler.items()))

        koerper = root.bRepBodies.item(0)
        fehler = [f.name for f in root.features if f.healthState != 0]

        ui.messageBox(
            'Sternenmuster erzeugt\n\n'
            'Seed: %d\n'
            'Loecher: %d  (%s)\n'
            'Schnittebenen: %d\n'
            'Uebersprungen: %d\n'
            'Restvolumen: %.2f cm3\n'
            'Fehlerhafte Features: %s'
            % (SEED, erzeugt, aufstellung, len(ebenen), uebersprungen,
               koerper.physicalProperties.volume,
               ', '.join(fehler) if fehler else 'keine'))

    except:
        if ui:
            ui.messageBox('Fehler im Generator:\n\n%s' % traceback.format_exc())

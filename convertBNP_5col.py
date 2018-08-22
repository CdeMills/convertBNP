#!/usr/bin/env python
# -*- coding:utf-8 -*-
#
# auteur             2012 -- 2016 twolaw_at_free_dot_fr
#                    2017 -- 2018 Pascal Dupuis <cdemills@gmail.com>
# nom                convertBNP_5col.py
# description        Lit les relevés bancaires de la BNP en PDF dans le répertoire courant pour en générer des CSV
#                    Nécessite le fichier pdftotext.exe en version 3.03 issu de l'archive xpdf (gratuit, GPL2)
# ------------------
# 10-nov-2013 v1     pour python3
# 26-nov-2014 v1.1   ajout de la version "_4col" qui sépare crédit et débits en 2 colonnes distinctes
# 28-jan-2015 v1.2   correction du bug "Mixing iteration and read methods would lose data"
# ------------------
# chaque opération bancaire contient 4 éléments :
#
#   - date : string de type 'JJ/MM/AAAA'
#   - description de l'opération : string
#   - valeur de débit : string
#   - valeur de crédit : string
#
# fichiers PDF de la forme RCHQ_101_300040012300001234567_20131026_2153.PDF

# Copyright 2012-2016 twolaw_at_free_dot_fr
# Copyright 2017-2018 Pascal Dupuis <cdemills@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.

import pdb

import argparse, os, re, subprocess, shutil, sys
import xlsxwriter
import locale
from datetime import datetime as dt

# Le motif des fichiers à traiter, à remplacer ou a transmettre via le fichier
# "prefixe_compte.txt" ou via l'argument --prefixe
PREFIXE_COMPTE = "123456789"

CSV_SEP        = ";"
deja_en_csv    = ""
deja_en_xlsx   = ""

# quelques motifs qui seront cherchés ... souvent
pattern = re.compile('(\W+)')
monnaie_pat = re.compile('Monnaie du compte\s*: (\w*)')
nature_pat = re.compile('D\s*ate\s+N\s*ature\s+des\s+')
footer_pat = re.compile('BNP PARIBAS.*au capital')

locale.setlocale(locale.LC_NUMERIC, '')
# the decimal point in use
dp = locale.localeconv()['decimal_point']

if os.name == 'nt':
    PDFTOTEXT = 'pdftotext.exe'
    PREFIXE_CSV    = "Relevé BNP "
else: 
    PDFTOTEXT = 'pdftotext'
    PREFIXE_CSV    = "Relevé_BNP_"

class uneOperation:
    """Une opération bancaire = une date, un descriptif,
    une valeur de débit, une valeur de crédit et un interrupteur de validité"""

    def __init__(self, date="", desc="", value="", debit=0.0, credit=0.0):
        self.date   = date
        self.date_valeur = ""
        self.date_oper = ""
        self.desc   = desc
        self.value  = value
        self.debit  = debit
        self.credit = credit
        self.valide = True
        if not len(self.date) >= 10 or int(self.date[:2]) > 31 or int(self.date[3:4]) > 12:
            self.valide = False

    def estRemplie(self, operation=[]):
        ## return len(self.date) >=10 and len(desc) > 0 and len(value) > 0 \
        ##    and (len(credit) > 0 or len(debit) > 0)
        resu = len(self.date) >=10 and (self.credit > 0.0 or self.debit > 0.0) 
        if resu:
            # this one is OK, fill its description
            if len(operation):
                if 0 == len(self.desc):
                    self.desc = ' '.join(operation)
                    for num, date in enumerate(operation):
                        try:
                            date_oper = dt.strptime(date, '%d/%m/%y').strftime('%d/%m/%Y')
                            self.date_oper = date_oper
                            break;
                        except ValueError as e:
                            if 1 == num:  # du 020316
                                try:
                                    date_oper = dt.strptime(date, '%d%m%y').strftime('%d/%m/%Y')
                                    self.date_oper = date_oper
                                    break;
                                except ValueError as e:
                                    continue      
                            continue                 
        return resu


class UnReleve:
    """Un relevé de compte est une liste d'opérations bancaires
    sur une durée définie"""
    def __init__(self, nom="inconnu"):
        self.nom = nom
        self.liste = []

    def ajoute(self, Ope):
        """Ajoute une opération à la fin de la liste du relevé bancaire"""
        self.liste.append(Ope)

    def ajoute_from_TXT(self, fichier_txt, annee, mois, verbosity=False, basedir=None):
        """Parse un fichier TXT pour en extraire les
        opérations bancaires et les mettre dans le relevé"""
        print('[txt->    ] Lecture    : '+fichier_txt)

        if basedir:
            fichier_txt = os.path.join(basedir, fichier_txt)

        with open(fichier_txt, 'r') as file:
            Table = False
            vide = 0
            page_width = 0
            num = 0

            if verbosity > 1:
                pdb.set_trace()

            # ignore les lignes avec les coordonnées et le blabla
            for ligne in file:
                num = num + 1
                monnaie = monnaie_pat.search(ligne)
                if monnaie:
                    monnaie = monnaie.group(1)
                    break

            # detect bad pdf->txt conversions and abort
            if not(isinstance(monnaie, str)):
                print("Le fichier {} semble mal formatté !".format(fichier_txt))
                input("Bye bye :(")
                exit()

            # à présent, en-tête et SOLDE  / Date / valeur
            for ligne in file:
                num = num + 1
                # this is a cut-and-paste of lines 239 -- 245
                if nature_pat.search(ligne):
                    Table = True        # where back analysing data
                    Date_pos = re.search('D\s*ate', ligne).start()
                    Nature_pos = re.search('N\s*ature', ligne).start()
                    dernier = re.search('V\s*aleur', ligne)
                    Valeur_pos = dernier.start()
                    Debit_pos = dernier.end() + 1
                    Credit_pos = re.search('D\s*ébit  ', ligne).end() + 1
                    page_width = len(ligne)
                    continue
                if re.search('SOLDE\s+', ligne):
                    break

            operation = ligne.split()
            for Ope, date in enumerate(operation):
                try:
                    basedate = dt.strptime(date, '%d.%m.%Y').strftime('%d/%m/%Y')
                    break
                except ValueError as e:
                    continue

            # montant ?
            la_valeur = locale.atof(''.join(operation[Ope+1:]))
            ligne = ' '.join(operation[:Ope+1])

            # dans quel sens ?      
            if re.match('crediteur', operation[1], re.IGNORECASE):
                Ope = uneOperation(basedate, ligne, "", 0.0, la_valeur)
                solde_init = la_valeur
            elif re.match('debiteur', operation[1], re.IGNORECASE):
                Ope = uneOperation(basedate, ligne, "", la_valeur, 0.0)
                solde_init = -la_valeur
            else:
                raise ValueError(ligne+"ne peut pas être interprétée")

            # crée une entrée avec le solde initial
            self.ajoute(Ope)
            if verbosity:
                print('{}({}): {}'.format(num, len(ligne), ligne))
                print('Solde initial: {}  au {}'.format(solde_init, basedate))
                print('Date:{} -- desc:{} -- debit {} -- credit {}'.format(Ope.date, Ope.desc,
                                                                           Ope.debit, Ope.credit))

            if verbosity > 1:
                pdb.set_trace()

            Ope = uneOperation()
            date = ""
            operation = []
            la_date = ""

            somme_cred = 0.0  # To check sum of cred
            somme_deb = 0.0   # To check sum of deb

            ## pdb.set_trace()
            for ligne in file:
                num = num+1
                if len(ligne) < 2:           # ligne vide, trait du tableau
                    vide = vide + 1
                    continue

                if Table:
                    # detect footer
                    eot = footer_pat.search(ligne)
                    if eot is None:
                        # This is one of the strange lines with a numeric code at the end
                        eot = (0 == len(ligne[:Debit_pos].split()))
                    if (eot):
                        if verbosity > 1:
                            pdb.set_trace()
                        Table = False
                        if len(operation) > 0:
                            if Ope.estRemplie(operation):  # on ajoute la précédente
                                self.ajoute(Ope)           # opération si elle est valide
                                if verbosity:   
                                    print('Date:{} -- desc:{} -- debit {} -- credit {}'.format(Ope.date, Ope.desc,  
                                                                                           Ope.debit, Ope.credit))      
                                Ope = uneOperation()
                                date = ""
                                la_date = ""
                                operation = []
                        continue

                if Table is False:
                    # search for new page header -- compute actual page width
                    if nature_pat.search(ligne): 
                        Table = True        # where back analysing data
                        Date_pos = re.search('D\s*ate', ligne).start()
                        Nature_pos = re.search('N\s*ature', ligne).start()
                        dernier = re.search('V\s*aleur', ligne)
                        Valeur_pos = dernier.start()
                        Debit_pos = dernier.end() + 1
                        Credit_pos = re.search('D\s*ébit  ', ligne).end() + 1
                        page_width = len(ligne)
                    continue

                # this line ends the table
                if re.match('.*?total des montants\s', ligne, re.IGNORECASE):
                    if verbosity:
                        print('{}({}): {}'.format(num, len(ligne), ligne))
                    if verbosity > 1:
                        pdb.set_trace()
                    break
                if re.match('.*?total des operations\s', ligne, re.IGNORECASE):
                    if verbosity:   
                        print('{}({}): {}'.format(num, len(ligne), ligne))
                    if verbosity > 1:   
                        pdb.set_trace()
                    break

                if verbosity:
                    print('{}({}): {}'.format(num, len(ligne), ligne))

                date_ou_pas = ligne[:Nature_pos].split()  # premier caractères de la ligne (date?)
                if 1 == len(date_ou_pas):
                    date_ou_pas = pattern.split(date_ou_pas[0])

                # si une ligne se termine par un montant, il faut l'extraire pour qu'il reste la
                # date valeur
                dernier = pattern.split(ligne[Debit_pos:].strip())
                # this was
                # dernier = ligne[-22:].split()    # derniers caractères (valeur?)
                if 1 == len(dernier):
                    dernier = pattern.split(dernier[0])
                # put your debug code here
                # if "MUTUELLE GENERALE" in ligne:
                #     if verbosity:
                #         pdb.set_trace()

                if estArgent(dernier):
                    # si l'operation précédente est complète, on la sauve
                    if Ope.estRemplie(operation):
                        self.ajoute(Ope)          # opération si elle est valide
                        if verbosity:                                                       
                            print('Date:{} -- desc:{} -- debit {} -- credit {}'.format(Ope.date, Ope.desc,  
                                                                                       Ope.debit, Ope.credit))
                        Ope = uneOperation()
                        operation = []                # we are on a new op
                    la_valeur = list2valeur(dernier)
                    try:
                        # there are odd and even pages. That's odd !
                        if dp in ligne[Debit_pos:Credit_pos]:
                            Ope.debit = locale.atof(la_valeur)
                            somme_deb += Ope.debit            
                        else:                
                            Ope.credit = locale.atof(la_valeur)
                            somme_cred += Ope.credit
                            
                    except ValueError as e:
                        print('Failed to convert {} to a float: {}'.format(la_valeur, e))
                    previous_ligne = ligne    
                    ligne = ligne[:Debit_pos]     # truncate the money amount

                if estDate(date_ou_pas):          # est-ce une date
                    date_valeur = ligne[Valeur_pos:Debit_pos].split() # il y a aussi une date valeur
                    if 1 == len(date_valeur):

                        date_valeur = pattern.split(date_valeur[0])
                    if Ope.estRemplie(operation):          # on ajoute la précédente 
                        self.ajoute(Ope)          # opération si elle est valide
                        if verbosity:    
                            print('Date:{} -- desc:{} -- debit {} -- credit {}'.format(Ope.date, Ope.desc,  
                                                                                       Ope.debit, Ope.credit))      
                        Ope = uneOperation()

                    operation = []                # we are on a new op
                    la_date = ''
                    date = date_ou_pas

                operation.extend(ligne[Nature_pos:Valeur_pos].split())   

                if date : # si on a deja trouvé une date
                    la_date = list2date(date, annee, mois)
                    date = ""
                    if (len(date_valeur) < 3):
                        date_valeur = dernier
 
                    if (len(date_valeur) < 3):
                        print('line 223')
                        print(ligne)
                        print(ligne[85:91])
                        print(ligne[109:114])
                        print(date_valeur)
                        pdb.set_trace()

                    la_date_valeur = list2date(date_valeur, annee, mois)
                    Ope.date = la_date
                    Ope.date_valeur = la_date_valeur

            # end of main table             
            if Ope.estRemplie(operation):         # on ajoute la précédente
                if verbosity:
                    print('Date:{} -- desc:{} -- debit {} -- credit {}'.format(Ope.date, Ope.desc,  
                                                                               Ope.debit, Ope.credit))      
                self.ajoute(Ope)          # opération si elle est valide     
        
            if verbosity:
                print('Exited main loop')
                print('{}({}): {}'.format(num, len(ligne), ligne))
                if verbosity > 1:
                    pdb.set_trace()

            # this part may fail if there is no "Débit" field  
            operation = ligne.split()
            start = 3
            count = 3
            for num, elem in enumerate(operation[count:]):
                # pre-increment count as [start:count] goes one element
                # before count
                count = count + 1
                if dp in elem:
                    if (1 == len(elem)):        # in the old listing, there were extraneous spaces
                        count = count + 1
                    break
            dernier = pattern.split(ligne[Debit_pos:Credit_pos].strip())
            # check it's really a debit field
            if (estArgent(dernier)):        
                le_debit = ''.join(operation[start:count])
                start = count
                count = start
                for elem in operation[count:]:
                    count = count + 1
                    if dp in elem:
                        if (1 == len(elem)):        # in the old listings, there were extraneous spaces
                            count = count + 1
                        break

                le_credit = ''.join(operation[start:count])
            else:
                le_debit  = ''
                le_credit = ''.join(operation[start:count])
                    
            # convert both data, if present
            if (len(le_debit) > 0):
                try:
                    le_debit = locale.atof(le_debit)
                except ValueError as e:
                    print('Failed to convert {} to a float: {}'.format(le_debit, e))
            else:
                le_debit = 0.0
                    
            if (len(le_credit) > 0):
                try:
                    le_credit = locale.atof(le_credit)
                except ValueError as e:
                    print('Failed to convert {} to a float: {}'.format(le_credit, e))
            else:
                le_credit = 0.0

            # here, we have "solde .. au
            for ligne in file:
                if re.search('SOLDE\s+', ligne): 
                    break

            operation = ligne.split()
            for num, date in enumerate(operation):
                try:
                    basedate = dt.strptime(date, '%d.%m.%Y').strftime('%d/%m/%Y')
                    break;
                except ValueError as e:
                    continue

            # montant ?
            try:
                la_valeur = locale.atof(''.join(operation[num+1:]))
                ligne = ' '.join(operation[:num+1])
            except ValueError as e:
                print(operation)
                pdb.set_trace()

            # dans quel sens ?
            if re.match('crediteur', operation[1], re.IGNORECASE):
                Ope = uneOperation(basedate, ligne, "", 0.0, la_valeur)
                solde_final = la_valeur
            elif re.match('debiteur', operation[1], re.IGNORECASE):
                Ope = uneOperation(basedate, ligne, "", la_valeur, 0.0)
                solde_final = -la_valeur
            else:
                raise ValueError(ligne+" ne peut pas être interprétée")
            # check that solde_deb = le_debit;
            if abs(somme_deb - le_debit) > .01:
                if verbosity:
                    print("La somme des débits {} n'est pas égale au débit totat {}".format(somme_deb, le_debit))         
                    pdb.set_trace()
                else:
                    raise ValueError('La somme des débits {} n''est pas égale au débit total {}'.format(somme_deb, le_debit))

            # check that solde_cred = le_credit;
            if abs(somme_cred - le_credit) > .01:
                if verbosity:
                    print("La somme des crédits {} n'est pas égale au crédit total {}".format(somme_cred, le_credit))               
                    pdb.set_trace()
                else:
                    raise ValueError('La somme des crédits {} n''est pas égale au crédit totat {}'.format(somme_cred, le_credit))                    
            # check that solde_init - le_credit + le_debit == solde_final
            mouvements = solde_init - le_debit + le_credit
            if abs(solde_final - mouvements) > .01:
                if verbosity:
                    print("La somme des mouvements {} n'arrive pas au solde final {}".format(mouvements, solde_final))      
                    pdb.set_trace()
                else:
                    raise ValueError('La somme des mouvements n''arrive pas au solde final {}'.format(mouvements, solde_final))
            
            # duplicate the current operation
            OpeTot = uneOperation(basedate, "TOTAL DES MONTANTS", "", le_debit, le_credit)
            OpeTot.desc = "TOTAL DES MONTANTS"
            OpeTot.debit = le_debit
            OpeTot.credit = le_credit
            # dump it
            self.ajoute(OpeTot)

            # crée une entrée avec le solde final
            self.ajoute(Ope)
            if verbosity: 
                print('{}({}): {}'.format(num, len(ligne), ligne))
                print('Solde final: {}  au {}'.format(solde_final, basedate))

    def genere_CSV(self, filename="", basedir=None):
        """crée un fichier CSV qui contiendra les opérations du relevé
        si ce CSV n'existe pas deja"""
        if filename == "":
            filename = self.nom
        filename_csv = filename + ".csv"
        if filename_csv not in deja_en_csv:
            print('[   ->csv ] Export     : '+filename_csv)
            if basedir:
                filename_csv=os.path.join(basedir, filename_csv)
            with open(filename_csv, "w") as file:
                file.write("Date"+CSV_SEP+"Date_Valeur"+CSV_SEP+"Date_Oper"+CSV_SEP+"Débit"+CSV_SEP+"Crédit"+CSV_SEP+"Opération\n")
                for Ope in self.liste:
                    file.write(Ope.date+CSV_SEP+Ope.date_valeur+CSV_SEP+Ope.date_oper+CSV_SEP+str(Ope.debit)+CSV_SEP+str(Ope.credit)+CSV_SEP+Ope.desc+"\n")
                file.close()
        filename_xlsx = filename + ".xlsx"
        if filename_xlsx not in deja_en_xlsx:
            print('[   ->xlsx] Export     : '+filename_xlsx)
            # pdb.set_trace()
            if basedir:
                filename_xlsx=os.path.join(basedir, filename_xlsx)
            workbook = xlsxwriter.Workbook(filename_xlsx)
            worksheet = workbook.add_worksheet()
            worksheet.set_column(0, 2, 12)
            worksheet.set_column(3, 4, 10)
            worksheet.set_column(5, 5, 64)
            cell_format = workbook.add_format({'bold': True})
            worksheet.write_row('A1', ["Date", "Date_Valeur", "Date_Oper", "Débit", "Crédit", "Opération"], cell_format);
            row = 1
            for Ope in self.liste[:-2]:
                worksheet.write_row(row, 0, [Ope.date, Ope.date_valeur, Ope.date_oper, Ope.debit, Ope.credit, Ope.desc])
                row = row + 1
            # generate a control formula
            Ope = self.liste[-2]
            worksheet.write(row, 0, Ope.date)
            worksheet.write(row, 5, 'Somme de contrôle')
            # EXELL formula are stored in english but displayed in locale
            worksheet.write_formula(row, 3, '=SUM(D3:D'+str(row)+')')
            worksheet.write_formula(row, 4, '=SUM(E3:E'+str(row)+')')
            row = row + 1
            for Ope in self.liste[-2:]:
                worksheet.write_row(row, 0, [Ope.date, Ope.date_valeur, Ope.date_oper, Ope.debit, Ope.credit, Ope.desc])
                row = row + 1
            workbook.close()


def extraction_PDF(pdf_file, deja_en_txt, temp, basedir=None):
    """Lit un relevé PDF et le convertit en fichier TXT du même nom
    s'il n'existe pas deja"""
    txt_file = pdf_file[:-3]+"txt"

    if basedir:
        pdf_file = os.path.join(basedir, pdf_file)
        abs_file = os.path.join(basedir, txt_file)
    else:
        abs_file = txt_file

    if txt_file not in deja_en_txt:
        print('[pdf->txt ] Conversion : '+pdf_file)
        subprocess.call([PDFTOTEXT, '-layout', pdf_file, abs_file])
        print('[pdf->txt ]              terminée, taille  ' +
              str(os.path.getsize(abs_file)) + ' octets')
        temp.append(txt_file)


def estDate(liste):
    """ Attend un format ['JJ', '.' 'MM']"""
    if len(liste) != 3:
        return False
    if len(liste[0]) == 2 and liste[1] == '.' and len(liste[2]) == 2:
        return True
    return False

def estArgent(liste):
    """ Attend un format ['[0-9]*', ',', '[0-9][0-9]'] """
    if len(liste) < 3:
        return False
    if dp in liste[-2]:
        return True
    return False


def list2date(liste, annee, mois):
    """renvoie un string"""
    if (len(liste) < 3):
        print('line 297')
        print(liste)
        pdb.set_trace()

    if mois == '01' and liste[2] == '12':
        return liste[0]+'/'+liste[2]+'/'+str(int(annee)-1)
    else:
        return liste[0]+'/'+liste[2]+'/'+annee


def list2valeur(liste):
    """renvoie un string"""
    liste_ok = [x.strip() for x in liste if x != '.']
    return "".join(liste_ok)


def filtrer(liste, filetype):
    """Renvoie une liste triée des fichiers qui correspondent à l'extension donnée en paramètre"""
    files = [fich for fich in liste if fich.split('.')[-1].lower() == filetype]
    files.sort()
    return files

def mois_dispos(liste):
    """Renvoie une liste des relevés disponibles de la forme
    [['2012', '10', '11', '12']['2013', '01', '02', '03', '04']]"""
    liste_tout = []
    les_annees = []

    for releve in liste:
        operation = releve.split('.')   # strip the extension
        operation = operation[0].split('_')   # get chunks
        if "FRAIS" in operation[0]:
            continue
        for num, val in enumerate(operation[1:]):
            if PREFIXE_COMPTE not in val:
                continue
            # the next element contains the date
            annee = operation[num+2][0:4]
            mois  = operation[num+2][4:6]
            if annee not in les_annees:
                les_annees.append(annee)
                liste_annee = [annee, mois]
                liste_tout.append(liste_annee)
            else:
                liste_tout[les_annees.index(annee)].append(mois)
    liste_tout.sort()
    return liste_tout

# fonction inutilisée
def est_dispo(annee, mois, liste):
    """Verifie si le relevé de ce mois/année est disponible
    dans la liste donnée"""
    for annee_de_liste in liste:
        if annee == annee_de_liste[0]:
            if mois in annee_de_liste:
                return True
    return False

def affiche(liste):
    """Affiche à l'écran les mois dont les relevés sont disponibles"""
    print("Relevés disponibles:")
    for annee in liste:
        ligne_12 = ['  ']*12
        for i in annee:
            if len(i) == 2:
                ligne_12[int(i)-1] = i
        ligne = annee[0]+': '+' '.join(ligne_12)
        print(ligne)
    print("")

def getVarFromFile(filename):
    global PREFIXE_COMPTE
   


# On demarre ici
def main(*args, **kwargs):
    print('\n******************************************************')
    print('*   Convertisseur de relevés bancaires BNP Paribas   *')
    print('********************  PDF -> CSV/XLSX  ***************\n')

    if shutil.which(PDFTOTEXT) is None:
        print("Fichier {} absent !".format(PDFTOTEXT))
        input("Bye bye :(")
        exit()

    parser = argparse.ArgumentParser()
    parser.add_argument("--verbosity", type=int, default=0, help="increase output verbosity")
    parser.add_argument("--prefixe", help="prefixe des fichiers à traiter")
    parser.add_argument("--dir", help="répertoire des fichiers à traiter")
    myargs = parser.parse_args()

    global PREFIXE_COMPTE
    
    chemin = os.getcwd()
    if myargs.dir:
        myargs.dir = os.path.expanduser(myargs.dir)
        if os.path.isabs(myargs.dir):
            chemin = myargs.dir
        else:
            chemin = os.path.join(chemin, myargs.dir)

    if myargs.prefixe:
        PREFIXE_COMPTE = myargs.prefixe
    else:
        if os.path.isfile('./prefixe_compte.txt'):
            with open('./prefixe_compte.txt', 'r') as file:
                PREFIXE_COMPTE = file.readline().strip()
        mes_pdfs = os.path.join(chemin, 'prefixe_compte.txt')
        if os.path.isfile(mes_pdfs):
            with open(mes_pdfs, 'r') as file:
                PREFIXE_COMPTE = file.readline().strip()

    fichiers = os.listdir(chemin)

    mes_pdfs = filtrer(fichiers, 'pdf')
    deja_en_txt = filtrer(fichiers, 'txt')
    deja_en_csv = filtrer(fichiers, 'csv')
    deja_en_xlsx = filtrer(fichiers, 'xlsx')

    mes_mois_disponibles = mois_dispos(mes_pdfs)
    mes_mois_deja_en_txt = mois_dispos(deja_en_txt)

    if len(mes_mois_disponibles) == 0:
        print("Il n'y a pas de relevés de compte en PDF dans le répertoire")
        print(chemin + "\n")
        print("contenant " + PREFIXE_COMPTE + " avant le champs 'date'")
        print("\nIl faut placer les fichiers convertBNP.py et pdftotext.exe")
        print("à côté des fichiers de relevé de compte en PDF et adapter")
        print("la ligne 48 (PREFIXE_COMPTE = XXXXX) du fichier convertBNP.py")
        print("pour la faire correspondre à votre numéro de compte.\n")
        input("Bye bye :(")
        exit()

    affiche(mes_mois_disponibles)
    touch = 0
    temp_list = []

    # on convertit tous les nouveaux relevés PDF en TXT sauf si CSV deja dispo
    for releve in mes_pdfs:
        operation = releve.split('.')   # strip the extension
        operation = operation[0].split('_')   # get chunks
        if "FRAIS" in operation[0]:
            continue
        for num, val in enumerate(operation[1:]):
            if PREFIXE_COMPTE not in val:
                continue
            annee = operation[num+2][0:4]
            mois  = operation[num+2][4:6]
            csv = PREFIXE_CSV+annee+'-'+mois+".csv"
            xlsx= PREFIXE_CSV+annee+'-'+mois+".xlsx"
            if csv not in deja_en_csv:
                touch = touch + 1
                extraction_PDF(releve, deja_en_txt, temp_list, myargs.dir)
            elif xlsx not in deja_en_xlsx:
                touch = touch + 1
                extraction_PDF(releve, deja_en_txt, temp_list, myargs.dir)
    if touch != 0:
        print("")

    # on remet à jour la liste de TXT
    fichiers = os.listdir(chemin)
    deja_en_txt = filtrer(fichiers, 'txt')
    mes_mois_deja_en_txt = mois_dispos(deja_en_txt)

    # on convertit tous les nouveaux TXT en CSV
    for txt in deja_en_txt:
        operation = txt.split('.')   # strip the extension
        operation = operation[0].split('_')   # get chunks
        if "FRAIS" in operation[0]:
            continue
        for num, val in enumerate(operation[1:]):
            if PREFIXE_COMPTE not in val:
                continue
            # the next element contains the date
            annee = operation[num+2][0:4]
            mois  = operation[num+2][4:6]
            csv = PREFIXE_CSV+annee+'-'+mois+".csv"
            xlsx= PREFIXE_CSV+annee+'-'+mois+".xlsx"
            if csv not in deja_en_csv:
                releve = UnReleve()
                releve.ajoute_from_TXT(txt, annee, mois, myargs.verbosity, myargs.dir)
                releve.genere_CSV(PREFIXE_CSV+annee+'-'+mois, myargs.dir)
            elif xlsx not in deja_en_xlsx: 
                releve = UnReleve()
                releve.ajoute_from_TXT(txt, annee, mois, myargs.verbosity, myargs.dir)
                releve.genere_CSV(PREFIXE_CSV+annee+'-'+mois, myargs.dir)

    # on efface les fichiers TXT
    if len(temp_list):
        print("[txt-> x  ] Nettoyage\n")
        for txt in temp_list:
            if myargs.dir:
                txt = os.path.join(myargs.dir, txt)
            os.remove(txt)

    if touch == 0:
        input("Pas de nouveau relevé. Bye bye.")
    else:
        print(str(touch)+" relevés de comptes convertis.")
        input("Terminé. Bye bye.")

    # EOF

    return 0


if __name__== "__main__":
    sys.exit(main(sys.argv[1:]))

##
# @file   Placer.py
# @author Yibo Lin
# @date   Apr 2018
# @brief  Main file to run the entire placement flow. 
#

import matplotlib 
matplotlib.use('Agg')
import os
import sys 
import csv
import time 
import numpy as np 
import logging
import pickle
# for consistency between python2 and python3
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
	sys.path.append(root_dir)
import dreamplace.configure as configure 
import Params 
import PlaceDB
import NonLinearPlace 
import pdb 

def place(params):
    """
    @brief Top API to run the entire placement flow. 
    @param params parameters 
    """

    assert (not params.gpu) or configure.compile_configurations["CUDA_FOUND"] == 'TRUE', \
            "CANNOT enable GPU without CUDA compiled"

    np.random.seed(params.random_seed)
    # read database
    tt = time.time()  
    placedb = PlaceDB.PlaceDB()
    placedb(params)

    if params.csv_input:
        with open(params.csv_input) as csvfile:
            for row in csv.reader(csvfile, delimiter=','):
                name, x, y, orientation = row[0], row[1], row[2], row[3]
                node_id = placedb.node_name2id_map[name]
                placedb.node_x[node_id] = x
                placedb.node_y[node_id] = y
                placedb.node_orient[node_id] = orientation

    logging.info("reading database takes %.2f seconds" % (time.time()-tt))

    # solve placement 
    tt = time.time()
    placer = NonLinearPlace.NonLinearPlace(params, placedb)
    logging.info("non-linear placement initialization takes %.2f seconds" % (time.time()-tt))
    metrics = placer(params, placedb)
    logging.warning("non-linear placement takes %.2f seconds" % (time.time()-tt))

    # write placement solution 
    path = "%s/%s" % (params.result_dir, params.design_name())
    if not os.path.exists(path):
        os.system("mkdir -p %s" % (path))
    gp_out_file = os.path.join(path, "%s.gp.%s" % (params.design_name(), params.solution_file_suffix()))
    placedb.write(params, gp_out_file)
    return metrics

    # call external detailed placement
    # TODO: support more external placers, currently only support 
    # 1. NTUplace3/NTUplace4h with Bookshelf format 
    # 2. NTUplace_4dr with LEF/DEF format 
    if params.detailed_place_engine and os.path.exists(params.detailed_place_engine):
        logging.info("Use external detailed placement engine %s" % (params.detailed_place_engine))
        if params.solution_file_suffix() == "pl" and any(dp_engine in params.detailed_place_engine for dp_engine in ['ntuplace3', 'ntuplace4h']): 
            dp_out_file = gp_out_file.replace(".gp.pl", "")
            # add target density constraint if provided 
            target_density_cmd = ""
            if params.target_density < 1.0 and not params.routability_opt_flag:
                target_density_cmd = " -util %f" % (params.target_density)
            cmd = "%s -aux %s -loadpl %s %s -out %s -noglobal %s" % (params.detailed_place_engine, params.aux_input, gp_out_file, target_density_cmd, dp_out_file, params.detailed_place_command)
            logging.info("%s" % (cmd))
            tt = time.time()
            os.system(cmd)
            logging.info("External detailed placement takes %.2f seconds" % (time.time()-tt))

            if params.plot_flag: 
                # read solution and evaluate 
                placedb.read_pl(params, dp_out_file+".ntup.pl")
                iteration = len(metrics)
                pos = placer.init_pos
                pos[0:placedb.num_physical_nodes] = placedb.node_x
                pos[placedb.num_nodes:placedb.num_nodes+placedb.num_physical_nodes] = placedb.node_y
                hpwl, density_overflow, max_density = placer.validate(placedb, pos, iteration)
                logging.info("iteration %4d, HPWL %.3E, overflow %.3E, max density %.3E" % (iteration, hpwl, density_overflow, max_density))
                placer.plot(params, placedb, iteration, pos)
        elif 'ntuplace_4dr' in params.detailed_place_engine:
            dp_out_file = gp_out_file.replace(".gp.def", "")
            cmd = "%s" % (params.detailed_place_engine)
            for lef in params.lef_input:
                if "tech.lef" in lef:
                    cmd += " -tech_lef %s" % (lef)
                else:
                    cmd += " -cell_lef %s" % (lef)
            cmd += " -floorplan_def %s" % (gp_out_file)
            cmd += " -verilog %s" % (params.verilog_input)
            cmd += " -out ntuplace_4dr_out"
            cmd += " -placement_constraints %s/placement.constraints" % (os.path.dirname(params.verilog_input))
            cmd += " -noglobal %s ; " % (params.detailed_place_command)
            cmd += "mv ntuplace_4dr_out.fence.plt %s.fense.plt ; " % (dp_out_file)
            cmd += "mv ntuplace_4dr_out.init.plt %s.init.plt ; " % (dp_out_file)
            cmd += "mv ntuplace_4dr_out %s.ntup.def ; " % (dp_out_file)
            cmd += "mv ntuplace_4dr_out.ntup.overflow.plt %s.ntup.overflow.plt ; " % (dp_out_file)
            cmd += "mv ntuplace_4dr_out.ntup.plt %s.ntup.plt ; " % (dp_out_file)
            if os.path.exists("%s/dat" % (os.path.dirname(dp_out_file))):
                cmd += "rm -r %s/dat ; " % (os.path.dirname(dp_out_file))
            cmd += "mv dat %s/ ; " % (os.path.dirname(dp_out_file))
            logging.info("%s" % (cmd))
            tt = time.time()
            os.system(cmd)
            logging.info("External detailed placement takes %.2f seconds" % (time.time()-tt))
        else:
            logging.warning("External detailed placement only supports NTUplace3/NTUplace4dr API")
    elif params.detailed_place_engine:
        logging.warning("External detailed placement engine %s or aux file NOT found" % (params.detailed_place_engine))

    return metrics

if __name__ == "__main__":
    """
    @brief main function to invoke the entire placement flow. 
    """
    logging.root.name = 'DREAMPlace'
    logging.basicConfig(level=logging.WARNING, format='[%(levelname)-7s] %(name)s - %(message)s', stream=sys.stdout)
    params = Params.Params()
    # params.printWelcome()
    if len(sys.argv) == 1 or '-h' in sys.argv[1:] or '--help' in sys.argv[1:]:
        params.printHelp()
        exit()
    elif len(sys.argv) > 3:
        logging.error("One input parameters in json format in required")
        params.printHelp()
        exit()

    # load parameters 
    params.load(sys.argv[1])
    if len(sys.argv) == 3:
        params.csv_input = sys.argv[2]
    logging.info("parameters = %s" % (params))
    # control numpy multithreading
    os.environ["OMP_NUM_THREADS"] = "%d" % (params.num_threads)

    # run placement 
    tt = time.time()
    place(params)
    logging.info("placement takes %.3f seconds" % (time.time()-tt))

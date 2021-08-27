import io
import logging

import numpy as np
import polars as pl
from polars import lit, col, when

import pygef.plot_utils as plot
import pygef.utils as utils
from pygef import been_jefferies, robertson
from pygef.grouping import GroupClassification

logger = logging.getLogger(__name__)


MAP_QUANTITY_NUMBER_COLUMN_NAME_CPT = {
    1: "penetration_length",
    2: "qc",  # 2
    3: "fs",  # 3
    4: "friction_number",  # 4
    5: "u1",  # 5
    6: "u2",  # 6
    7: "u3",  # 7
    8: "inclination",  # 8
    9: "inclination_ns",  # 9
    10: "inclination_ew",  # 10
    11: "corrected_depth",  # 11
    12: "time",  # 12
    13: "corrected_qc",  # 13
    14: "net_cone_resistance",  # 14
    15: "pore_ratio",  # 15
    16: "cone_resistance_number",  # 16
    17: "weight_per_unit_volume",  # 17
    18: "initial_pore_pressure",  # 18
    19: "total_vertical_soil_pressure",  # 19
    20: "effective_vertical_soil_pressure",
    21: "inclination_in_x_direction",
    22: "inclination_in_y_direction",
    23: "electric_conductivity",
    31: "magnetic_field_x",
    32: "magnetic_field_y",
    33: "magnetic_field_z",
    34: "total_magnetic_field",
    35: "magnetic_inclination",
    36: "magnetic_declination",
    99: "classification_zone_robertson_1990",
    # found in:#COMPANYID= Fugro GeoServices B.V., NL005621409B08, 31
    131: "speed",  # found in:COMPANYID= Multiconsult, 09073590, 31
    135: "Temperature_c",  # found in:#COMPANYID= Inpijn-Blokpoel,
    250: "magneto_slope_y",  # found in:COMPANYID= Danny, Tjaden, 31
    251: "magneto_slope_x",
}  # found in:COMPANYID= Danny, Tjaden, 31

COLUMN_NAMES_BORE = [
    "depth_top",  # 1
    "depth_bottom",  # 2
    "lutum_percentage",  # 3
    "silt_percentage",  # 4
    "sand_percentage",  # 5
    "gravel_percentage",  # 6
    "organic_matter_percentage",  # 7
    "sand_median",  # 8
    "gravel_median",
]  # 9
MAP_QUANTITY_NUMBER_COLUMN_NAME_BORE = dict(enumerate(COLUMN_NAMES_BORE, 1))

COLUMN_NAMES_BORE_CHILD = [
    "depth_top",  # 1
    "depth_bottom",  # 2
    "undrained_shear_strength",  # 3
    "vertical_permeability",  # 4
    "horizontal_permeability",  # 5
    "effective_cohesion_at_x%_strain",  # 6
    "friction_angle_at_x%_strain",  # 7
    "water_content",  # 8
    "dry_volumetric_mass",  # 9
    "wet_volumetric_mass",  # 10
    "d_50",  # 11
    "d_60/d_10_uniformity",  # 12
    "d_90/d_10_gradation",  # 13
    "dry_volumetric_weight",  # 14
    "wet_volumetric_weight",  # 15
    "vertical_strain",
]  # 16
MAP_QUANTITY_NUMBER_COLUMN_NAME_BORE_CHILD = dict(enumerate(COLUMN_NAMES_BORE_CHILD, 1))

dict_soil_type_rob = {
    "Peat": 1,
    "Clays - silty clay to clay": 2,
    "Silt mixtures - clayey silt to silty clay": 3,
    "Sand mixtures - silty sand to sandy silt": 4,
    "Sands - clean sand to silty sand": 5,
    "Gravelly sand to dense sand": 6,
}

dict_soil_type_been = {
    "Peat": 1,
    "Clays": 2,
    "Clayey silt to silty clay": 3,
    "Silty sand to sandy silt": 4,
    "Sands: clean sand to silty": 5,
    "Gravelly sands": 6,
}


class ParseGEF:
    """
    The ParseGEF file can be used to parse a *.gef file and use it as an ParseGEF object.

    The gef parser is built following the conventional format described in:
    https://publicwiki.deltares.nl/download/attachments/102204318/GEF-CPT.pdf?version=1&modificationDate=1409732008000&api=v2

    For more information on initialization of this class type:
    print(ParseGEF.__init__.__doc__)

    To check the available methods, type:
        print(dir(ParseGEF))

    **Attributes**:
    The ParseGEF class accept as input the *.gef file of a bore or cpt type.

    Some attributes are common for the both types, other are specific to the type(cpt or bore).

    Check the list below for the available attributes.

        ** Common attributes:**
        type: str
            Type of the gef file
        project_id: str
            Project id
        x: float
            X coordinate respect to the coordinate system
        y: float
            Y coordinate respect to the coordinate system
        zid: float
            Z coordinate respect to the height system
        height_system: float
            Type of coordinate system, 31000 is NAP
        file_date: datatime.datetime
            Start date time
        test_id: str
            Identifying name of gef file.
        s: str
            String version of gef file.

        ** Cpt attributes:**
        *Always present:*
            df: polars.DataFrame
                DataFrame containing the same column contained in the original .gef file and
                some additional columns [depth, elevation_with_respect_to_nap]

                Tip: Use depth column instead of the penetration_length, the depth is corrected
                with the inclination(if present).

                Note that the Friction ratio is always calculated from the fs and qc values and not parsed from the file.

                If this attribute is called after the classify method the columns relative to the classification
                are also contained.

        *Not always present* default: None
        The description is added only for the most important attributes, for the others check:
        https://publicwiki.deltares.nl/download/attachments/102204318/GEF-CPT.pdf?version=1&modificationDate=1409732008000&api=v2

            cpt_class: str
                Cpt class. The format is not standard so it might be not always properly parsed.
            column_void: str
                It is the definition of no value for the gef file
            nom_surface_area_cone_tip: float
                Nom. surface area of cone tip [mm2]
            nom_surface_area_friction_element: float
                Nom. surface area of friction casing [mm2]
            net_surface_area_quotient_of_the_cone_tip: float
                Net surface area quotient of cone tip [-]
            net_surface_area_quotient_of_the_friction_casing: float
                Net surface area quotient of friction casing [-]
            distance_between_cone_and_centre_of_friction_casing: float
            friction_present: float
            ppt_u1_present: float
            ppt_u2_present: float
            ppt_u3_present: float
            inclination_measurement_present: float
            use_of_back_flow_compensator: float
            type_of_cone_penetration_test: float
            pre_excavated_depth: float
                 Pre excavate depth [m]
            groundwater_level: float
                Ground water level [m]
            water_depth_offshore_activities: float
            end_depth_of_penetration_test: float
            stop_criteria: float
            zero_measurement_cone_before_penetration_test: float
            zero_measurement_cone_after_penetration_test: float
            zero_measurement_friction_before_penetration_test: float
            zero_measurement_friction_after_penetration_test: float
            zero_measurement_ppt_u1_before_penetration_test: float
            zero_measurement_ppt_u1_after_penetration_test: float
            zero_measurement_ppt_u2_before_penetration_test: float
            zero_measurement_ppt_u2_after_penetration_test: float
            zero_measurement_ppt_u3_before_penetration_test: float
            zero_measurement_ppt_u3_after_penetration_test: float
            zero_measurement_inclination_before_penetration_test: float
            zero_measurement_inclination_after_penetration_test: float
            zero_measurement_inclination_ns_before_penetration_test: float
            zero_measurement_inclination_ns_after_penetration_test: float
            zero_measurement_inclination_ew_before_penetration_test: float
            zero_measurement_inclination_ew_after_penetration_test : float
            mileage: float
        ** Bore attributes:**
            df: polars.DataFrame
                DataFrame containing the columns: [
                                                    "depth_top",
                                                    "depth_bottom",
                                                    "soil_code",
                                                    "gravel_component",
                                                    "sand_component",
                                                    "clay_component",
                                                    "loam_component",
                                                    "peat_component",
                                                    "silt_component",
                                                    "remarks",
                                                ]
    """

    def __init__(self, path=None, string=None, old_column_names=False):
        """
        Base class of gef parser. It switches between the cpt or borehole parser.

        It takes as input either the path to the gef file or the gef file as string.

        Parameters
        ----------
        path: str
            Path to the *.gef file.
        string: str
            String version of the *.gef file.
        old_column_names: bool
            Use deprecated column names.
        """
        self.path = path
        self.df = None
        self.net_surface_area_quotient_of_the_cone_tip = None
        self.pre_excavated_depth = None

        if string is None:
            with open(path, encoding="utf-8", errors="ignore") as f:
                string = f.read()
        self.s = string

        end_of_header = utils.parse_end_of_header(self.s)
        header_s, data_s = self.s.split(end_of_header)
        self.zid = utils.parse_zid_as_float(header_s)
        self.height_system = utils.parse_height_system(header_s)
        self.x = utils.parse_xid_as_float(header_s)
        self.y = utils.parse_yid_as_float(header_s)
        self.file_date = utils.parse_file_date(header_s)
        self.test_id = utils.parse_test_id(header_s)

        self.type = utils.parse_gef_type(string)
        if self.type == "cpt":
            parsed = ParseCPT(header_s, data_s, self.zid, self.height_system)
        elif self.type == "bore":
            parsed = ParseBORE(header_s, data_s)
        elif self.type == "borehole-report":
            raise ValueError(
                "The selected gef file is a GEF-BOREHOLE-Report. Can only parse "
                "GEF-CPT-Report and GEF-BORE-Report. Check the PROCEDURECODE."
            )
        else:
            raise ValueError(
                "The selected gef file is not a cpt nor a borehole. "
                "Check the REPORTCODE or the PROCEDURECODE."
            )

        self.__dict__.update(parsed.__dict__)

        # Convert all NaN to None and drop them
        self.df = self.df.fill_nan(None).drop_nulls()

        if old_column_names:
            # Use deprecated naming standards
            self.df = self.df.rename(
                {
                    "gravel_component": "G",
                    "sand_component": "S",
                    "clay_component": "C",
                    "loam_component": "L",
                    "peat_component": "P",
                    "silt_component": "SI",
                    "remarks": "Remarks",
                }
            )

    def plot(
        self,
        classification=None,
        water_level_NAP=None,
        water_level_wrt_depth=None,
        min_thickness=None,
        p_a=0.1,
        new=True,
        show=False,
        figsize=(11, 8),
        df_group=None,
        do_grouping=False,
        grid_step_x=None,
        dpi=100,
        colors=None,
        z_NAP=False,
    ):
        """
        Plot the *.gef file and return matplotlib.pyplot.figure .

        It works both with a cpt or borehole type file. If no argument it is passed it returns:
        - CPT: plot of qc [MPa] and Friction ratio [%]
        - BOREHOLE: plot of soil components over the depth.

        Parameters
        ----------
        classification: str, only for cpt type
            If classification ("robertson", "been_jefferies") is specified a subplot is added with the classification
            for each cpt row.
        water_level_NAP: float, only for cpt type, necessary for the classification: give this or water_level_wrt_depth
            Water level with respect to NAP
        water_level_wrt_depth: float, only for cpt type, necessary for the classification: give this or water_level_NAP
            Water level with respect to the ground_level [0], it should be a negative value.
        min_thickness: float, only for cpt type, optional for the classification [m]
            If specified together with the do_grouping set to True, a group classification is added to the plot.
            The grouping is a simple algorithm that merge all the layers < min_thickness with the last above one >
            min_thickness.
            In order to not make a big error do not use a value bigger then 0.2 m
        p_a: float, only for cpt type, optional for the classification
            Atmospheric pressure. Default: 0.1 MPa.
        new: bool, only for cpt type, optional for the classification default:True
            If True and the classification is robertson, the new(2016) implementation of robertson is used.
        show: bool
            If True the plot is showed, else the matplotlib.pytplot.figure is returned
        figsize: tuple
            Figsize of the plot, default (11, 8).
        df_group: polars.DataFrame, only for cpt type, optional for the classification
            Use this argument to plot a defined soil layering next to the other subplots.
            It should contain the columns:
                - layer
                    Name of layer, should be either BeenJefferies of Robertson soil type,
                    if it is different then also the argument colors should be passed.
                - z_centr_NAP
                    Z value of the middle of the layer
                - thickness
                    Thickness of the layer
        do_grouping: bool, only for cpt type, optional for the classification
            If True a group classification is added to the plot.
        grid_step_x: float, only for cpt type, default: None
            Grid step for qc and Fr subplots.
        dpi: int
            Dpi figure
        colors: dict
            Dictionary containing the colors associated to each soil type, if specified
        z_NAP: bool
            If True the Z-axis is with respect to NAP.
        Returns
        -------
        matplotlib.pyplot.figure
        """
        if (
            self.type == "cpt"
        ):  # todo: refactor arguments, the arguments connected to each other should be given as a dict or tuple, check order
            if classification is None:
                df = self.df
            else:
                df = self.classify(
                    classification=classification,
                    water_level_NAP=water_level_NAP,
                    water_level_wrt_depth=water_level_wrt_depth,
                    p_a=p_a,
                    new=new,
                )

                if df_group is None and do_grouping is True:
                    df_group = self.classify(
                        classification=classification,
                        water_level_NAP=water_level_NAP,
                        water_level_wrt_depth=water_level_wrt_depth,
                        p_a=p_a,
                        new=new,
                        do_grouping=True,
                        min_thickness=min_thickness,
                    )

            return plot.plot_cpt(
                df,
                df_group,
                classification,
                show=show,
                figsize=figsize,
                grid_step_x=grid_step_x,
                colors=colors,
                dpi=dpi,
                z_NAP=z_NAP,
            )

        elif self.type == "bore":
            return plot.plot_bore(self.df, figsize=figsize, show=show, dpi=dpi)

        else:
            raise ValueError(
                "The selected gef file is not a cpt nor a borehole. "
                "Check the REPORTCODE or the PROCEDURECODE."
            )

    def classify(
        self,
        classification,
        water_level_NAP=None,
        water_level_wrt_depth=None,
        p_a=0.1,
        new=True,
        do_grouping=False,
        min_thickness=None,
    ):
        """
        Classify each row of the cpt type.

        Parameters
        ----------
        classification: str
            Specify the classification, possible choices : "robertson", "been_jefferies".
        water_level_NAP: float, only for cpt type, necessary for the classification: give this or water_level_wrt_depth
            Water level with respect to NAP
        water_level_wrt_depth: float, only for cpt type, necessary for the classification: give this or water_level_NAP
            Water level with respect to the ground_level [0], it should be a negative value.
        p_a: float
            Atmospheric pressure. Default: 0.1 MPa.
        new: bool, default:True
            If True and the classification is robertson, the new(2016) implementation of robertson is used.
        do_grouping: bool,  optional for the classification
            If True a group classification is added to the plot.
        min_thickness: float, optional for the classification [m]
            If specified together with the do_grouping set to True, a group classification is added to the plot.
            The grouping is a simple algorithm that merge all the layers < min_thickness with the last above one > min_thickness.
            In order to not make a big error do not use a value bigger then 0.2 m

        Returns
        -------
        df: polars.DataFrame
        If do_grouping is True a polars.DataFrame with the grouped layer is returned otherwise a polars.DataFrame with
        a classification for each row is returned.

        """
        # todo: refactor arguments, the arguments connected to each other should be given as a dict or tuple, check order
        water_level_and_zid_NAP = dict(water_level_NAP=water_level_NAP, zid=self.zid)

        if water_level_NAP is None and water_level_wrt_depth is None:
            water_level_wrt_depth = -1
            logger.warning(
                f"You did not input the water level, a default value of -1 m respect to the ground is used."
                f" Change it using the kwagr water_level_NAP or water_level_wrt_depth."
            )
        if min_thickness is None:
            min_thickness = 0.2
            logger.warning(
                f"You did not input the accepted minimum thickness, a default value of 0.2 m is used."
                f" Change it using th kwarg min_thickness"
            )

        if classification == "robertson":
            df = robertson.classify(
                self.df,
                water_level_and_zid_NAP=water_level_and_zid_NAP,
                water_level_wrt_depth=water_level_wrt_depth,
                new=new,
                area_quotient_cone_tip=self.net_surface_area_quotient_of_the_cone_tip,
                pre_excavated_depth=self.pre_excavated_depth,
                p_a=p_a,
            )
            if do_grouping:
                return GroupClassification(self.zid, df, min_thickness).df_group
            return df

        elif classification == "been_jefferies":
            df = been_jefferies.classify(
                self.df,
                water_level_and_zid_NAP=water_level_and_zid_NAP,
                water_level_wrt_depth=water_level_wrt_depth,
                area_quotient_cone_tip=self.net_surface_area_quotient_of_the_cone_tip,
                pre_excavated_depth=self.pre_excavated_depth,
            )
            if do_grouping:
                return GroupClassification(self.zid, df, min_thickness).df_group
            return df
        else:
            raise ValueError(
                f"Could not find {classification}. Check the spelling or classification not defined in the library"
            )

    def __str__(self):
        return (
            "test id: {} \n"
            "type: {} \n"
            "(x,y): ({:.2f},{:.2f}) \n"
            "First rows of dataframe: \n {}".format(
                self.test_id, self.type, self.x, self.y, self.df.head(n=2)
            )
        )


class ParseCPT:
    def __init__(self, header_s, data_s, zid, height_system, old_column_names=True):
        """
        Parser of the cpt file.

        :param header_s: (str) Header of the file
        :param data_s: (str) Data of the file
        :param zid: (flt) Z attribute.
        :param old_column_names: (bool) Use deprecated column names.
        """

        self.type = "cpt"
        self.project_id = utils.parse_project_type(header_s, "cpt")
        self.cone_id = utils.parse_cone_id(header_s)
        self.cpt_class = utils.parse_cpt_class(header_s)
        self.column_void = utils.parse_column_void(header_s)
        self.nom_surface_area_cone_tip = utils.parse_measurement_var_as_float(
            header_s, 1
        )
        self.nom_surface_area_friction_element = utils.parse_measurement_var_as_float(
            header_s, 2
        )
        self.net_surface_area_quotient_of_the_cone_tip = utils.parse_measurement_var_as_float(
            header_s, 3
        )
        self.net_surface_area_quotient_of_the_friction_casing = utils.parse_measurement_var_as_float(
            header_s, 4
        )
        self.distance_between_cone_and_centre_of_friction_casing = utils.parse_measurement_var_as_float(
            header_s, 5
        )
        self.friction_present = utils.parse_measurement_var_as_float(header_s, 6)
        self.ppt_u1_present = utils.parse_measurement_var_as_float(header_s, 7)
        self.ppt_u2_present = utils.parse_measurement_var_as_float(header_s, 8)
        self.ppt_u3_present = utils.parse_measurement_var_as_float(header_s, 9)
        self.inclination_measurement_present = utils.parse_measurement_var_as_float(
            header_s, 10
        )
        self.use_of_back_flow_compensator = utils.parse_measurement_var_as_float(
            header_s, 11
        )
        self.type_of_cone_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 12
        )
        self.pre_excavated_depth = utils.parse_measurement_var_as_float(header_s, 13)
        self.groundwater_level = utils.parse_measurement_var_as_float(header_s, 14)
        self.water_depth_offshore_activities = utils.parse_measurement_var_as_float(
            header_s, 15
        )
        self.end_depth_of_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 16
        )
        self.stop_criteria = utils.parse_measurement_var_as_float(header_s, 17)
        self.zero_measurement_cone_before_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 20
        )
        self.zero_measurement_cone_after_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 21
        )
        self.zero_measurement_friction_before_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 22
        )
        self.zero_measurement_friction_after_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 23
        )
        self.zero_measurement_ppt_u1_before_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 24
        )
        self.zero_measurement_ppt_u1_after_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 25
        )
        self.zero_measurement_ppt_u2_before_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 26
        )
        self.zero_measurement_ppt_u2_after_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 27
        )
        self.zero_measurement_ppt_u3_before_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 28
        )
        self.zero_measurement_ppt_u3_after_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 29
        )
        self.zero_measurement_inclination_before_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 30
        )
        self.zero_measurement_inclination_after_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 31
        )
        self.zero_measurement_inclination_ns_before_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 32
        )
        self.zero_measurement_inclination_ns_after_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 33
        )
        self.zero_measurement_inclination_ew_before_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 34
        )
        self.zero_measurement_inclination_ew_after_penetration_test = utils.parse_measurement_var_as_float(
            header_s, 35
        )
        self.mileage = utils.parse_measurement_var_as_float(header_s, 41)

        self.df = (
            self.parse_data(header_s, data_s)
            .pipe(replace_column_void, self.column_void)
            .pipe(correct_pre_excavated_depth, self.pre_excavated_depth)
            .pipe(self.correct_depth_with_inclination)
            .select(
                [
                    pl.all().exclude("depth"),
                    self.make_depth_absolute(),
                    self.calculate_elevation_with_respect_to_nap(zid, height_system),
                ]
            )
            .pipe(self.calculate_friction_number)
        )

        if old_column_names:
            # Use deprecated naming standards
            self.df = self.df.rename(
                {"elevation_with_respect_to_nap": "elevation_with_respect_to_NAP"}
            )

    @staticmethod
    def calculate_friction_number(df):
        if "fs" in df.columns and "qc" in df.columns:
            df["friction_number"] = df["fs"] / df["qc"] * 100
        if "friction_number" not in df.columns:
            df["friction_number"] = np.zeros(df.shape[0])

        return df

    @staticmethod
    def calculate_elevation_with_respect_to_nap(zid, height_system):
        if zid is not None and height_system == 31000:
            return (pl.lit(zid) - pl.col("depth")).alias(
                "elevation_with_respect_to_nap"
            )

        return None

    @staticmethod
    def correct_depth_with_inclination(df):
        if "corrected_depth" in df.columns:
            df = df.rename(mapping={"corrected_depth": "depth"})
        elif "inclination" in df.columns:
            inclination = df.select(pl.col("inclination").fill_none(0))[:-1]
            diff_t_depth = np.diff(df["penetration_length"]) * np.cos(
                np.radians(inclination)
            )
            # corrected depth
            df["depth"] = np.concatenate(
                [
                    np.array([df["penetration_length"][0]]),
                    np.array([df["penetration_length"][0]]) + np.cumsum(diff_t_depth),
                ]
            )
        else:
            df["depth"] = df["penetration_length"]

        return df

    @staticmethod
    def parse_data(header_s, data_s, columns_number=None, columns_info=None):
        if columns_number is None and columns_info is None:
            columns_number = utils.parse_columns_number(header_s)
            if columns_number is not None:
                columns_info = []
                for column_number in range(1, columns_number + 1):
                    columns_info.append(
                        utils.parse_column_info(
                            header_s, column_number, MAP_QUANTITY_NUMBER_COLUMN_NAME_CPT
                        )
                    )
        new_data = data_s.replace("!", "")
        separator = utils.find_separator(header_s)

        return pl.read_csv(
            io.StringIO(new_data),
            sep=separator,
            new_columns=columns_info,
            has_headers=False,
        )

    @staticmethod
    def make_depth_absolute():
        return pl.col("depth").map(lambda x: np.abs(x))


class ParseBORE:
    def __init__(self, header_s, data_s, old_column_names=False):
        """
        Parser of the borehole file.

        :param header_s: (str) Header of the file
        :param data_s: (str) Data of the file
        :param old_column_names: (bool) Use deprecated column names
        """
        self.type = "bore"
        self.project_id = utils.parse_project_type(header_s, "bore")

        # This is usually not correct for the boringen
        columns_number = utils.parse_columns_number(header_s)
        column_separator = utils.parse_column_separator(header_s)
        record_separator = utils.parse_record_separator(header_s)
        data_s_rows = data_s.split(record_separator)
        data_rows_soil = self.extract_soil_info(
            data_s_rows, columns_number, column_separator
        )

        self.df = (
            self.parse_data_column_info(
                header_s, data_s, column_separator, columns_number
            )
            .pipe(self.parse_data_soil_code, data_rows_soil)
            .pipe(self.parse_data_soil_type, data_rows_soil)
            .pipe(self.parse_add_info_as_string, data_rows_soil)
            .pipe(self.parse_soil_quantification, data_rows_soil)
            .drop(
                [
                    "sand_median",
                    "gravel_median",
                    "lutum_percentage",
                    "silt_percentage",
                    "sand_percentage",
                    "gravel_percentage",
                    "organic_matter_percentage",
                    "soil_type",
                ]
            )
        )

        if old_column_names:
            # Use deprecated naming standards
            self.df = self.df.rename(
                {
                    "gravel_component": "G",
                    "sand_component": "S",
                    "clay_component": "C",
                    "loam_component": "L",
                    "peat_component": "P",
                    "silt_component": "SI",
                }
            )

    @staticmethod
    def parse_add_info_as_string(df, data_rows_soil):
        df["remarks"] = [
            utils.parse_add_info("".join(row[1::])) for row in data_rows_soil
        ]

        return df

    @staticmethod
    def extract_soil_info(data_s_rows, columns_number, column_separator):
        return list(
            map(
                lambda x: x.split(column_separator)[columns_number:-1], data_s_rows[:-1]
            )
        )

    @staticmethod
    def parse_data_column_info(
        header_s, data_s, sep, columns_number, columns_info=None
    ):
        if columns_info is None:
            col = list(
                map(
                    lambda x: utils.parse_column_info(
                        header_s, x, MAP_QUANTITY_NUMBER_COLUMN_NAME_BORE
                    ),
                    range(1, columns_number + 1),
                )
            )
            return pl.read_csv(
                io.StringIO(data_s),
                sep=sep,
                new_columns=col,
                has_headers=False,
                projection=list(range(0, len(col))),
            )
        else:
            return pl.read_csv(
                io.StringIO(data_s),
                sep=sep,
                new_columns=columns_info,
                has_headers=False,
            )

    @staticmethod
    def parse_data_soil_type(df, data_rows_soil):
        df["soil_type"] = list(
            map(lambda x: utils.create_soil_type(x[0]), data_rows_soil)
        )

        return df

    @staticmethod
    def parse_data_soil_code(df, data_rows_soil):
        df["soil_code"] = list(
            map(lambda x: utils.parse_soil_code(x[0]), data_rows_soil)
        )

        return df

    @staticmethod
    def parse_soil_quantification(df, data_rows_soil):
        data = np.array([utils.soil_quantification(x[0]) for x in data_rows_soil])

        # Gravel
        df["gravel_component"] = data[:, 0]
        # Sand
        df["sand_component"] = data[:, 1]
        # Clay
        df["clay_component"] = data[:, 2]
        # Loam
        df["loam_component"] = data[:, 3]
        # Peat
        df["peat_component"] = data[:, 4]
        # Silt
        df["silt_component"] = data[:, 5]

        return df


def replace_column_void(lf: pl.LazyFrame, column_void) -> pl.LazyFrame:
    if column_void is None:
        return lf

    # TODO: what to do with multiple columnvoids?
    if isinstance(column_void, list):
        column_void = column_void[0]

    return (
        # Get all values matching column_void and change them to null
        lf.select(
            pl.when(pl.all() == pl.lit(column_void))
            .then(pl.lit(None))
            .otherwise(pl.all())
            .keep_name()
        )
        # Interpolate all null values
        .select(pl.all().interpolate())
        # Remove the rows with null values
        .drop_nulls()
    )


def correct_pre_excavated_depth(lf: pl.LazyFrame, pre_excavated_depth) -> pl.LazyFrame:
    if pre_excavated_depth is not None and pre_excavated_depth > 0:
        return lf.filter(col("penetration_length") >= pre_excavated_depth)
    return lf

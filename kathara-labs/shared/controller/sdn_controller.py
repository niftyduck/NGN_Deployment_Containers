
""" This code is launched by 'controller.startup' from kathara.

    When an event of type EventOFPSwitchFeatures (=switch sends
    OpenFlow messages with its ID and characteristics) happens,
    and the connection is currently in state CONFIG_DISPATCHER
    (=still configuring phase), it calls the function
    switch_features_handler().

    It uses the Default-deny, i.e. nothing gets forwarded unless
    explicitly allowed by higher-level rules by the orchestrator.
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3

class SDNController(app_manager.RyuApp):
    # Only talk to OpenFlow Protocol v1.3
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        parser = datapath.ofproto_parser

        # Match everything
        match = parser.OFPMatch()

        # Priority = 0 because the orchestrator rules must have larger priority
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=0,
            match=match,
            instructions=[]
        )

        # Send modification back to the switch
        datapath.send_msg(mod)
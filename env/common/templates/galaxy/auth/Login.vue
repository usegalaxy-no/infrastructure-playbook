<template>
    <div class="container">
        <div class="row justify-content-md-center">

            <div class="col">
               <h1>Welcome to <b>UseGalaxy.no</b> - a data analysis platform for life science data</h1>

               <p style="margin-top:20px">
                  This service is maintained by Elixir Norway and is for users from both the academia and industry sectors.
                  Extensive use from the industrial sector will have to be charged based on CPU hours - This model is under construction.
               </p>
               <p>
                  The service can be accessed using FEIDE login if your institution is FEIDE connected to the NeLS portal.
                  Users from the industry sector and international research collaborators that don't have FEIDE access can apply for a NeLS ID to get access.
               </p>
	       <p>
	       Questions can be directed to our <a href="https://elixir.no/helpdesk" target="_blank">helpdesk</a>.
	       </p>

               <a href="https://nels.bioinfo.no" target="_blank"><img src="/static/images/nels_logo_old.png" style="width:240px;margin-top:16px;"></a>
               <a href="https://galaxyproject.org" target="_blank"><img src="/static/images/galaxy_logo.png" style="width:292px;margin-top:16px;"></a>
               <a href="https://elixir.no" target="_blank"><img src="/static/images/elixir_no_logo.png" style="width:200px;margin-top:16px;"></a>
            </div>

            <template v-if="!confirmURL">
                <div class="col col-lg-6">
                    <b-alert :show="messageShow" :variant="messageVariant" v-html="messageText" />
                    <b-form id="login" @submit.prevent="submitGalaxyLogin()">
                        <b-card no-body header="Please log in with one of the options below">
                            <b-card-body>
			        <!-- standard internal galaxy login -->
				<!--
                                <div>                                    
                                    <b-form-group label="Public Name or Email Address">
                                        <b-form-input name="login" type="text" v-model="login" />
                                    </b-form-group>
                                    <b-form-group label="Password">
                                        <b-form-input name="password" type="password" v-model="password" />
                                        <b-form-text>
                                            Forgot password?
                                            <a @click="reset" href="javascript:void(0)" role="button"
                                                >Click here to reset your password.</a
                                            >
                                        </b-form-text>
                                    </b-form-group>
                                    <b-button name="login" type="submit">Login</b-button>
                                </div>
				-->
                                <div v-if="enable_oidc">
                                    <!-- OIDC login-->
                                    <external-login :login_page="true" />
                                </div>
                            </b-card-body>
                            <b-card-footer>
                                Don't have a FEIDE account? Apply for a NeLS ID by first clicking on "FEIDE or NeLS ID" above,
				then "Login with NeLS Identity" and finally "Apply for a NeLS Account"
                            </b-card-footer>
                        </b-card>
                    </b-form>

                    <b-modal centered id="duplicateEmail" ref="duplicateEmail" title="Duplicate Email" ok-only>
                        <p>
                            There already exists a user with this email. To associate this external login, you must
                            first be logged in as that existing account.
                        </p>

                        <p>
                            Reminder: Registration and usage of multiple accounts is tracked and such accounts are
                            subject to termination and data deletion. Connect existing account now to avoid possible
                            loss of data.
                        </p>
                        -->
                    </b-modal>
                </div>
            </template>

            <template v-else>
                <confirmation @setRedirect="setRedirect" />
            </template>

            <div v-if="show_welcome_with_login" class="col">
                <b-embed type="iframe" :src="welcome_url" aspect="1by1" />
            </div>
        </div>
    </div>
</template>

<script>
import axios from "axios";
import Vue from "vue";
import BootstrapVue from "bootstrap-vue";
import { getGalaxyInstance } from "app";
import { getAppRoot } from "onload";
import Confirmation from "components/login/Confirmation.vue";
import ExternalLogin from "components/User/ExternalIdentities/ExternalLogin.vue";

Vue.use(BootstrapVue);

export default {
    components: {
        ExternalLogin,
        Confirmation,
    },
    props: {
        show_welcome_with_login: {
            type: Boolean,
            required: false,
        },
        welcome_url: {
            type: String,
            required: false,
        },
    },
    data() {
        const galaxy = getGalaxyInstance();
        return {
            login: null,
            password: null,
            url: null,
            messageText: null,
            messageVariant: null,
            allowUserCreation: galaxy.config.allow_user_creation,
            redirect: galaxy.params.redirect,
            session_csrf_token: galaxy.session_csrf_token,
            enable_oidc: galaxy.config.enable_oidc,
        };
    },
    computed: {
        messageShow() {
            return this.messageText != null;
        },
        confirmURL() {
            var urlParams = new URLSearchParams(window.location.search);
            return urlParams.has("confirm") && urlParams.get("confirm") == "true";
        },
    },
    methods: {
        toggleLogin() {
            if (this.$root.toggleLogin) {
                this.$root.toggleLogin();
            }
        },
        submitGalaxyLogin(method) {
            if (localStorage.getItem("redirect_url")) {
                this.redirect = localStorage.getItem("redirect_url");
            }
            const rootUrl = getAppRoot();
            axios
                .post(`${rootUrl}user/login`, this.$data)
                .then((response) => {
                    if (response.data.message && response.data.status) {
                        alert(response.data.message);
                    }
                    if (response.data.expired_user) {
                        window.location = `${rootUrl}root/login?expired_user=${response.data.expired_user}`;
                    } else if (response.data.redirect) {
                        window.location = encodeURI(response.data.redirect);
                    } else {
                        window.location = `${rootUrl}`;
                    }
                })
                .catch((error) => {
                    this.messageVariant = "danger";
                    const message = error.response.data && error.response.data.err_msg;
                    this.messageText = message || "Login failed for an unknown reason.";
                });
        },
        setRedirect(url) {
            localStorage.setItem("redirect_url", url);
        },
        reset(ev) {
            const rootUrl = getAppRoot();
            ev.preventDefault();
            axios
                .post(`${rootUrl}user/reset_password`, { email: this.login })
                .then((response) => {
                    this.messageVariant = "info";
                    this.messageText = response.data.message;
                })
                .catch((error) => {
                    this.messageVariant = "danger";
                    const message = error.response.data && error.response.data.err_msg;
                    this.messageText = message || "Password reset failed for an unknown reason.";
                });
        },
    },
};
</script>
<style scoped>
.card-body {
    overflow: visible;
}
</style>
